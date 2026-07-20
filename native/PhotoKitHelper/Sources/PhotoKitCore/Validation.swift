import Foundation

public struct ValidatedImportFields: Equatable {
    public let itemID: String
    public let stagedPath: String
    public let role: String
    public let uti: String
}

public enum ImportFieldError: Error, Equatable {
    case malformed
    case unsupportedType
}

public enum ImportTransactionPlanError: Error, Equatable {
    case albumChangeUnavailable
}

public enum ImportMutationEvidenceStatus: String, Equatable {
    case createdIdentifierKnown = "created_identifier_known"
    case outcomeUnknown = "outcome_unknown"
    case notAttemptedAfterUnknown = "not_attempted_after_unknown"
}

public struct ImportMutationEvidence: Equatable {
    public let itemID: String
    public let localIdentifier: String?
    public let status: ImportMutationEvidenceStatus
    public let evidence: String
}

private let canonicalTypes: [String: (role: String, uti: String)] = [
    "jpg": ("photo", "public.jpeg"),
    "jpeg": ("photo", "public.jpeg"),
    "png": ("photo", "public.png"),
    "heic": ("photo", "public.heic"),
    "heif": ("photo", "public.heif"),
    "tif": ("photo", "public.tiff"),
    "tiff": ("photo", "public.tiff"),
    "gif": ("photo", "com.compuserve.gif"),
    "mov": ("video", "com.apple.quicktime-movie"),
    "mp4": ("video", "public.mpeg-4"),
    "m4v": ("video", "com.apple.m4v-video")
]

public func validateImportFields(_ item: [String: Any]) throws -> ValidatedImportFields {
    guard let itemID = item["item_id"] as? String, !itemID.isEmpty,
          let stagedPath = item["staged_path"] as? String, !stagedPath.isEmpty,
          let role = item["role"] as? String,
          let uti = item["uti"] as? String else {
        throw ImportFieldError.malformed
    }
    let ext = URL(fileURLWithPath: stagedPath).pathExtension.lowercased()
    guard let expected = canonicalTypes[ext], expected.role == role, expected.uti == uti else {
        throw ImportFieldError.unsupportedType
    }
    return ValidatedImportFields(itemID: itemID, stagedPath: stagedPath, role: role, uti: uti)
}

public func validateImportBatch(_ items: [[String: Any]]) throws -> [ValidatedImportFields] {
    guard !items.isEmpty else { throw ImportFieldError.malformed }
    return try items.map(validateImportFields)
}

public func executeValidatedImport<Result>(
    _ items: [[String: Any]],
    mutation: ([ValidatedImportFields]) throws -> Result
) throws -> Result {
    let validated = try validateImportBatch(items)
    return try mutation(validated)
}

public func dispatchImportPayload<Result>(
    _ payload: [String: Any],
    mutation: ([ValidatedImportFields], String) throws -> Result
) throws -> Result {
    guard let items = payload["items"] as? [[String: Any]],
          let albumIdentifier = payload["album_id"] as? String,
          !albumIdentifier.isEmpty else {
        throw ImportFieldError.malformed
    }
    return try executeValidatedImport(items) { validated in
        try mutation(validated, albumIdentifier)
    }
}

public func executeOrderedAlbumMutation<AlbumChange>(
    acquireAlbumChange: () -> AlbumChange?,
    registerCreations: (AlbumChange) -> Void
) throws {
    guard let albumChange = acquireAlbumChange() else {
        throw ImportTransactionPlanError.albumChangeUnavailable
    }
    registerCreations(albumChange)
}

public func executePerItemImport(
    _ items: [ValidatedImportFields],
    transaction: (ValidatedImportFields) throws -> String?
) -> [ImportMutationEvidence] {
    var results: [ImportMutationEvidence] = []
    var stopped = false
    for item in items {
        if stopped {
            results.append(ImportMutationEvidence(
                itemID: item.itemID,
                localIdentifier: nil,
                status: .notAttemptedAfterUnknown,
                evidence: "not_attempted_after_unknown"
            ))
            continue
        }
        do {
            if let identifier = try transaction(item) {
                results.append(ImportMutationEvidence(
                    itemID: item.itemID,
                    localIdentifier: identifier,
                    status: .createdIdentifierKnown,
                    evidence: "photokit_placeholder"
                ))
                continue
            }
            results.append(ImportMutationEvidence(
                itemID: item.itemID,
                localIdentifier: nil,
                status: .outcomeUnknown,
                evidence: "placeholder_missing_after_creation_registered"
            ))
            stopped = true
        } catch {
            results.append(ImportMutationEvidence(
                itemID: item.itemID,
                localIdentifier: nil,
                status: .outcomeUnknown,
                evidence: "transaction_outcome_unknown"
            ))
            stopped = true
        }
    }
    return results
}
