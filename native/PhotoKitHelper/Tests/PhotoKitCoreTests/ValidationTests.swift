import XCTest
@testable import PhotoKitCore

final class ValidationTests: XCTestCase {
    func testAcceptsCanonicalJPEG() throws {
        let value = try validateImportFields([
            "item_id": "src_1", "staged_path": "/tmp/photo.jpg",
            "role": "photo", "uti": "public.jpeg"
        ])
        XCTAssertEqual(value.uti, "public.jpeg")
    }

    func testRejectsMIMETypeInUTIField() {
        XCTAssertThrowsError(try validateImportFields([
            "item_id": "src_1", "staged_path": "/tmp/photo.jpg",
            "role": "photo", "uti": "image/jpeg"
        ]))
    }

    func testRejectsMissingField() {
        XCTAssertThrowsError(try validateImportFields(["item_id": "src_1"]))
    }

    func testRejectsMixedValidAndInvalidBatchBeforeMutation() {
        XCTAssertThrowsError(try validateImportBatch([
            [
                "item_id": "src_1", "staged_path": "/tmp/photo.jpg",
                "role": "photo", "uti": "public.jpeg"
            ],
            ["item_id": "src_2"]
        ]))
    }

    func testRejectsWrongRoleAndFieldType() {
        XCTAssertThrowsError(try validateImportFields([
            "item_id": "src_1", "staged_path": "/tmp/photo.jpg",
            "role": "video", "uti": "public.jpeg"
        ]))
        XCTAssertThrowsError(try validateImportFields([
            "item_id": 1, "staged_path": "/tmp/photo.jpg",
            "role": "photo", "uti": "public.jpeg"
        ]))
    }

    func testRejectsEmptyBatch() {
        XCTAssertThrowsError(try validateImportBatch([]))
    }

    func testMixedInvalidBatchNeverEntersProductionMutationSeam() {
        var mutationCalls = 0
        let payload: [String: Any] = [
            "album_id": "album-id",
            "items": [
                [
                    "item_id": "src_1", "staged_path": "/tmp/photo.jpg",
                    "role": "photo", "uti": "public.jpeg"
                ],
                ["item_id": "src_2"]
            ]
        ]
        XCTAssertThrowsError(try dispatchImportPayload(payload) { _, _ in
            mutationCalls += 1
        })
        XCTAssertEqual(mutationCalls, 0)
    }

    func testAlbumChangeIsAcquiredBeforeCreationRegistration() throws {
        var events: [String] = []
        try executeOrderedAlbumMutation(
            acquireAlbumChange: {
                events.append("album-change")
                return "change"
            },
            registerCreations: { _ in events.append("creations") }
        )
        XCTAssertEqual(events, ["album-change", "creations"])
    }

    func testMissingAlbumChangeNeverRegistersCreations() {
        var creationCalls = 0
        XCTAssertThrowsError(try executeOrderedAlbumMutation(
            acquireAlbumChange: { nil as String? },
            registerCreations: { _ in creationCalls += 1 }
        ))
        XCTAssertEqual(creationCalls, 0)
    }

    func testMissingPlaceholderStopsLaterTransactionsAndPreservesPriorEvidence() throws {
        let validated = try validateImportBatch([
            [
                "item_id": "src_1", "staged_path": "/tmp/one.jpg",
                "role": "photo", "uti": "public.jpeg"
            ],
            [
                "item_id": "src_2", "staged_path": "/tmp/two.jpg",
                "role": "photo", "uti": "public.jpeg"
            ],
            [
                "item_id": "src_3", "staged_path": "/tmp/three.jpg",
                "role": "photo", "uti": "public.jpeg"
            ]
        ])
        var transactionItemIDs: [String] = []
        let evidence = executePerItemImport(validated) { item in
            transactionItemIDs.append(item.itemID)
            return item.itemID == "src_2" ? nil : "local-\(item.itemID)"
        }

        XCTAssertEqual(evidence.map(\.status), [
            .createdIdentifierKnown, .outcomeUnknown, .notAttemptedAfterUnknown
        ])
        XCTAssertEqual(evidence.map(\.localIdentifier), [
            "local-src_1", nil, nil
        ])
        XCTAssertEqual(transactionItemIDs, ["src_1", "src_2"])
        XCTAssertEqual(
            evidence[1].evidence,
            "placeholder_missing_after_creation_registered"
        )
        XCTAssertEqual(evidence[2].evidence, "not_attempted_after_unknown")
    }

    func testPerItemTransactionErrorStopsLaterTransactions() throws {
        struct SyntheticError: Error {}
        let validated = try validateImportBatch([
            [
                "item_id": "src_1", "staged_path": "/tmp/one.jpg",
                "role": "photo", "uti": "public.jpeg"
            ],
            [
                "item_id": "src_2", "staged_path": "/tmp/two.jpg",
                "role": "photo", "uti": "public.jpeg"
            ]
        ])
        var transactionItemIDs: [String] = []
        let evidence = executePerItemImport(validated) { item in
            transactionItemIDs.append(item.itemID)
            if item.itemID == "src_1" { throw SyntheticError() }
            return "local-src_2"
        }

        XCTAssertEqual(evidence[0].status, .outcomeUnknown)
        XCTAssertEqual(evidence[0].evidence, "transaction_outcome_unknown")
        XCTAssertEqual(evidence[1].status, .notAttemptedAfterUnknown)
        XCTAssertNil(evidence[1].localIdentifier)
        XCTAssertEqual(transactionItemIDs, ["src_1"])
    }
}
