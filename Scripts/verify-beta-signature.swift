#!/usr/bin/env swift
import CryptoKit
import Foundation

let arguments = CommandLine.arguments
if arguments.count != 4 {
    fputs("Usage: verify-beta-signature.swift FILE PUBLIC_KEY SIGNATURE\n", stderr)
    exit(2)
}
do {
    guard let keyData = Data(base64Encoded: arguments[2]),
          let signature = Data(base64Encoded: arguments[3]), signature.count == 64 else {
        throw CocoaError(.fileReadCorruptFile)
    }
    let key = try Curve25519.Signing.PublicKey(rawRepresentation: keyData)
    let data = try Data(contentsOf: URL(fileURLWithPath: arguments[1]), options: .mappedIfSafe)
    guard key.isValidSignature(signature, for: data) else {
        fputs("Ed25519 signature verification failed.\n", stderr)
        exit(1)
    }
} catch {
    fputs("Cannot verify Ed25519 signature: \(error.localizedDescription)\n", stderr)
    exit(1)
}
