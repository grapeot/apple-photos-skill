import CryptoKit
import Foundation
import Photos
import PhotoKitCore

let protocolVersion = "1.0"

enum HelperError: Error {
    case invalidRequest(String)
    case permission(String)
    case notFound(String)
    case transaction(String)
    case resource(String)
    case stale(String)

    var code: String {
        switch self {
        case .invalidRequest: return "E_BACKEND_PROTOCOL"
        case .permission: return "E_PERMISSION_PHOTOS"
        case .notFound: return "E_NOT_FOUND"
        case .transaction: return "E_BACKEND_TRANSACTION"
        case .resource: return "E_RESOURCE_UNAVAILABLE"
        case .stale: return "E_PLAN_STALE"
        }
    }

    var message: String {
        switch self {
        case let .invalidRequest(value), let .permission(value), let .notFound(value),
             let .transaction(value), let .resource(value), let .stale(value):
            return value
        }
    }
}

func writeResponse(ok: Bool, result: Any? = nil, error: HelperError? = nil) {
    var response: [String: Any] = ["protocol_version": protocolVersion, "ok": ok]
    if let result {
        response["result"] = result
    }
    if let error {
        response["error"] = ["code": error.code, "message": error.message]
    }
    do {
        let data = try JSONSerialization.data(withJSONObject: response, options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    } catch {
        FileHandle.standardError.write(Data("Could not encode helper response.\n".utf8))
        exit(7)
    }
}

func requestAuthorization() throws {
    let semaphore = DispatchSemaphore(value: 0)
    var observed = PHAuthorizationStatus.notDetermined
    PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
        observed = status
        semaphore.signal()
    }
    semaphore.wait()
    guard observed == .authorized else {
        throw HelperError.permission("PhotoKit read/write authorization is required; status=\(observed.rawValue).")
    }
}

func payloadArray(_ payload: [String: Any], _ key: String) throws -> [String] {
    guard let values = payload[key] as? [String] else {
        throw HelperError.invalidRequest("Payload field '\(key)' must be a string array.")
    }
    return values
}

func fetchAssets(_ identifiers: [String]?, includeAll: Bool = false) -> [PHAsset] {
    let result: PHFetchResult<PHAsset>
    if includeAll {
        result = PHAsset.fetchAssets(with: nil)
    } else {
        result = PHAsset.fetchAssets(withLocalIdentifiers: identifiers ?? [], options: nil)
    }
    var assets: [PHAsset] = []
    result.enumerateObjects { asset, _, _ in assets.append(asset) }
    return assets
}

func fetchAlbum(_ identifier: String) throws -> PHAssetCollection {
    let result = PHAssetCollection.fetchAssetCollections(
        withLocalIdentifiers: [identifier],
        options: nil
    )
    guard result.count == 1, let album = result.firstObject else {
        throw HelperError.notFound("Album identifier did not resolve to exactly one album.")
    }
    return album
}

func resourceRole(_ type: PHAssetResourceType) -> String {
    switch type {
    case .photo, .fullSizePhoto, .alternatePhoto: return "photo"
    case .video, .fullSizeVideo: return "video"
    case .audio: return "audio"
    case .pairedVideo, .fullSizePairedVideo: return "paired_video"
    case .adjustmentData: return "adjustment"
    case .adjustmentBasePhoto, .adjustmentBaseVideo, .adjustmentBasePairedVideo:
        return "adjustment_base"
    case .photoProxy: return "photo_proxy"
    @unknown default: return "unknown_\(type.rawValue)"
    }
}

func assetMediaType(_ type: PHAssetMediaType) -> String {
    switch type {
    case .image: return "image"
    case .video: return "video"
    case .audio: return "audio"
    case .unknown: return "unknown"
    @unknown default: return "unknown"
    }
}

let isoFormatter: ISO8601DateFormatter = {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter
}()

func assetDictionary(_ asset: PHAsset) -> [String: Any] {
    let resources = PHAssetResource.assetResources(for: asset)
    let descriptors: [[String: Any]] = resources.map { resource in
        [
            "role": resourceRole(resource.type),
            "uti": resource.uniformTypeIdentifier,
            "original_filename": resource.originalFilename
        ]
    }
    return [
        "local_identifier": asset.localIdentifier,
        "media_type": assetMediaType(asset.mediaType),
        "original_filename": resources.first?.originalFilename ?? NSNull(),
        "date_taken": asset.creationDate.map(isoFormatter.string(from:)) ?? NSNull(),
        "date_modified": asset.modificationDate.map(isoFormatter.string(from:)) ?? NSNull(),
        "width": asset.pixelWidth,
        "height": asset.pixelHeight,
        "duration_ms": Int((asset.duration * 1000).rounded()),
        "favorite": asset.isFavorite,
        "hidden": asset.isHidden,
        "in_trash": false,
        "resource_descriptors": descriptors
    ]
}

func sha256File(_ url: URL) throws -> String {
    guard let stream = InputStream(url: url) else {
        throw HelperError.resource("Could not open an exported resource for hashing.")
    }
    stream.open()
    defer { stream.close() }
    var hasher = SHA256()
    let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024 * 1024)
    defer { buffer.deallocate() }
    while stream.hasBytesAvailable {
        let count = stream.read(buffer, maxLength: 1024 * 1024)
        if count < 0 {
            throw HelperError.resource(stream.streamError?.localizedDescription ?? "Resource hash read failed.")
        }
        if count == 0 { break }
        hasher.update(data: Data(bytes: buffer, count: count))
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

func safeComponent(_ value: String) -> String {
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "._-"))
    let filtered = value.unicodeScalars.map { allowed.contains($0) ? Character(String($0)) : "_" }
    return String(filtered).prefix(120).description
}

func writeResource(_ resource: PHAssetResource, to url: URL, network: Bool) -> Error? {
    let semaphore = DispatchSemaphore(value: 0)
    let options = PHAssetResourceRequestOptions()
    options.isNetworkAccessAllowed = network
    var observedError: Error?
    PHAssetResourceManager.default().writeData(for: resource, toFile: url, options: options) { error in
        observedError = error
        semaphore.signal()
    }
    semaphore.wait()
    return observedError
}

func probeLibrary() throws -> [String: Any] {
    try requestAuthorization()
    let allAssets = fetchAssets(nil, includeAll: true)
    let identifiers = allAssets.map(\.localIdentifier).sorted()
    var hasher = SHA256()
    for identifier in identifiers {
        hasher.update(data: Data(identifier.utf8))
        hasher.update(data: Data([0]))
    }
    let identifierDigest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
    return [
        "library_snapshot": [
            "kind": "system_photo_library_snapshot",
            "canonical_path": NSNull(),
            "is_system_library": true,
            "physical_identity_verified": false,
            "sentinel_asset_ids": Array(identifiers.prefix(3)),
            "asset_ids_sha256": "sha256:\(identifierDigest)",
            "asset_count": allAssets.count,
            "observed_at": isoFormatter.string(from: Date())
        ]
    ]
}

func listAlbums() throws -> [String: Any] {
    try requestAuthorization()
    let options = PHFetchOptions()
    let result = PHAssetCollection.fetchAssetCollections(with: .album, subtype: .any, options: options)
    var albums: [[String: Any]] = []
    result.enumerateObjects { album, _, _ in
        albums.append([
            "local_identifier": album.localIdentifier,
            "title": album.localizedTitle ?? "",
            "asset_count": PHAsset.fetchAssets(in: album, options: nil).count
            ,"can_add_assets": album.canPerform(.addContent)
        ])
    }
    albums.sort {
        let left = ($0["local_identifier"] as? String) ?? ""
        let right = ($1["local_identifier"] as? String) ?? ""
        return left < right
    }
    return ["albums": albums]
}

func fetchAssetDictionaries(_ payload: [String: Any]) throws -> [String: Any] {
    try requestAuthorization()
    let includeAll = (payload["include_all"] as? Bool) ?? false
    let identifiers = try payloadArray(payload, "local_identifiers")
    return ["assets": fetchAssets(identifiers, includeAll: includeAll).map(assetDictionary)]
}

func readResources(_ payload: [String: Any]) throws -> [String: Any] {
    try requestAuthorization()
    let identifiers = try payloadArray(payload, "local_identifiers")
    let network = (payload["network_access_allowed"] as? Bool) ?? false
    let requestedOutput = payload["output_directory"] as? String
    let root: URL
    let retainFiles: Bool
    if let requestedOutput {
        root = URL(fileURLWithPath: requestedOutput, isDirectory: true)
        retainFiles = true
    } else {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("apple-photos-helper-\(UUID().uuidString)", isDirectory: true)
        retainFiles = false
    }
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { if !retainFiles { try? FileManager.default.removeItem(at: root) } }
    var output: [[String: Any]] = []
    for asset in fetchAssets(identifiers) {
        for (index, resource) in PHAssetResource.assetResources(for: asset).enumerated() {
            let directory = root.appendingPathComponent(safeComponent(asset.localIdentifier), isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let name = "\(index)-\(safeComponent(resource.originalFilename))"
            let url = directory.appendingPathComponent(name)
            if let error = writeResource(resource, to: url, network: network) {
                output.append([
                    "local_identifier": asset.localIdentifier,
                    "role": resourceRole(resource.type),
                    "uti": resource.uniformTypeIdentifier,
                    "byte_count": 0,
                    "sha256": "",
                    "availability": "unavailable",
                    "path": NSNull(),
                    "backend_error": error.localizedDescription
                ])
                continue
            }
            let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            output.append([
                "local_identifier": asset.localIdentifier,
                "role": resourceRole(resource.type),
                "uti": resource.uniformTypeIdentifier,
                "byte_count": size,
                "sha256": try sha256File(url),
                "availability": "available",
                "path": retainFiles ? url.path : NSNull()
            ])
        }
    }
    return ["resources": output]
}

func importAssets(_ payload: [String: Any]) throws -> [String: Any] {
    try requestAuthorization()
    do {
        return try dispatchImportPayload(payload) { validated, albumIdentifier in
            try importValidatedAssets(validated, albumIdentifier: albumIdentifier)
        }
    } catch is ImportFieldError {
        throw HelperError.invalidRequest("Every import item must use a supported canonical UTI and role.")
    }
}

func importValidatedAssets(
    _ validated: [ValidatedImportFields], albumIdentifier: String
) throws -> [String: Any] {
    for item in validated {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: item.stagedPath, isDirectory: &isDirectory),
              !isDirectory.boolValue,
              FileManager.default.isReadableFile(atPath: item.stagedPath) else {
            throw HelperError.invalidRequest("Every staged import path must be a readable regular file.")
        }
    }
    let album = try fetchAlbum(albumIdentifier)
    guard album.canPerform(.addContent) else {
        throw HelperError.invalidRequest("Target album does not allow adding assets.")
    }
    let evidence = executePerItemImport(validated) { item in
        var placeholder: PHObjectPlaceholder?
        var transactionPlanError: Error?
        try PHPhotoLibrary.shared().performChangesAndWait {
            do {
                try executeOrderedAlbumMutation(
                    acquireAlbumChange: { PHAssetCollectionChangeRequest(for: album) }
                ) { change in
                    let request = PHAssetCreationRequest.forAsset()
                    let options = PHAssetResourceCreationOptions()
                    options.uniformTypeIdentifier = item.uti
                    let type: PHAssetResourceType = item.role == "video" ? .video : .photo
                    request.addResource(
                        with: type,
                        fileURL: URL(fileURLWithPath: item.stagedPath),
                        options: options
                    )
                    placeholder = request.placeholderForCreatedAsset
                    if let placeholder {
                        change.addAssets([placeholder] as NSArray)
                    }
                }
            } catch {
                transactionPlanError = error
            }
        }
        if let transactionPlanError {
            throw transactionPlanError
        }
        return placeholder?.localIdentifier
    }
    let knownCount = evidence.filter { $0.status == .createdIdentifierKnown }.count
    let unresolvedCount = evidence.count - knownCount
    let status = unresolvedCount == 0
        ? "succeeded" : (knownCount == 0 ? "outcome_unknown" : "partial")
    return [
        "status": status,
        "items": evidence.map { item -> [String: Any] in
            [
                "item_id": item.itemID,
                "local_identifier": item.localIdentifier.map { $0 as Any } ?? NSNull(),
                "status": item.status.rawValue,
                "evidence": item.evidence
            ]
        }
    ]
}

func addAssetsToAlbum(_ payload: [String: Any]) throws -> [String: Any] {
    try requestAuthorization()
    let identifiers = try payloadArray(payload, "local_identifiers")
    guard let albumIdentifier = payload["album_id"] as? String else {
        throw HelperError.invalidRequest("Album identifier is required.")
    }
    let assets = fetchAssets(identifiers)
    guard assets.count == identifiers.count else {
        throw HelperError.notFound("One or more assets were not found before album mutation.")
    }
    let album = try fetchAlbum(albumIdentifier)
    guard album.canPerform(.addContent) else {
        throw HelperError.invalidRequest("Target album does not allow adding assets.")
    }
    do {
        try PHPhotoLibrary.shared().performChangesAndWait {
            PHAssetCollectionChangeRequest(for: album)?.addAssets(assets as NSArray)
        }
    } catch {
        throw HelperError.transaction(error.localizedDescription)
    }
    return ["local_identifiers": identifiers]
}

func deleteAssets(_ payload: [String: Any]) throws -> [String: Any] {
    try requestAuthorization()
    guard let items = payload["items"] as? [[String: Any]], !items.isEmpty else {
        throw HelperError.invalidRequest("Delete requires a non-empty items array.")
    }
    let identifiers = try items.map { item -> String in
        guard let identifier = item["local_identifier"] as? String else {
            throw HelperError.invalidRequest("Every delete item requires an identifier.")
        }
        return identifier
    }
    let assets = fetchAssets(identifiers)
    guard assets.count == identifiers.count else {
        throw HelperError.notFound("One or more assets were not found before delete mutation.")
    }
    do {
        try PHPhotoLibrary.shared().performChangesAndWait {
            PHAssetChangeRequest.deleteAssets(assets as NSArray)
        }
    } catch {
        throw HelperError.transaction(error.localizedDescription)
    }
    return ["local_identifiers": identifiers]
}

func verifyAssets(_ payload: [String: Any]) throws -> [String: Any] {
    try requestAuthorization()
    let identifiers = try payloadArray(payload, "local_identifiers")
    let albumIdentifier = payload["album_id"] as? String
    var fetched = Dictionary(uniqueKeysWithValues: fetchAssets(identifiers).map { ($0.localIdentifier, $0) })
    var albumMembers = Set<String>()
    if let albumIdentifier {
        let album = try fetchAlbum(albumIdentifier)
        let result = PHAsset.fetchAssets(in: album, options: nil)
        result.enumerateObjects { asset, _, _ in albumMembers.insert(asset.localIdentifier) }
    }
    let results: [[String: Any]] = identifiers.map { identifier in
        let present = fetched.removeValue(forKey: identifier) != nil
        return [
            "local_identifier": identifier,
            "present": present,
            "in_album": albumIdentifier == nil ? NSNull() : albumMembers.contains(identifier)
        ]
    }
    return ["assets": results]
}

func dispatch(_ operation: String, payload: [String: Any]) throws -> Any {
    switch operation {
    case "probe-library": return try probeLibrary()
    case "list-albums": return try listAlbums()
    case "fetch-assets": return try fetchAssetDictionaries(payload)
    case "read-resources": return try readResources(payload)
    case "import-assets": return try importAssets(payload)
    case "add-assets-to-album": return try addAssetsToAlbum(payload)
    case "delete-assets": return try deleteAssets(payload)
    case "verify-assets": return try verifyAssets(payload)
    default: throw HelperError.invalidRequest("Unknown operation: \(operation)")
    }
}

do {
    guard let line = readLine(), let data = line.data(using: .utf8),
          let request = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          request["protocol_version"] as? String == protocolVersion,
          let operation = request["operation"] as? String,
          let payload = request["payload"] as? [String: Any] else {
        throw HelperError.invalidRequest("Expected one versioned JSON request on stdin.")
    }
    writeResponse(ok: true, result: try dispatch(operation, payload: payload))
} catch let error as HelperError {
    writeResponse(ok: false, error: error)
    exit(0)
} catch {
    writeResponse(ok: false, error: .invalidRequest(error.localizedDescription))
    exit(0)
}
