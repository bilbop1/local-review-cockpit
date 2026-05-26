import Foundation
import SwiftUI

func displayStatus(_ status: String) -> String {
    status.replacingOccurrences(of: "_", with: " ").capitalized
}

func displayUserStatus(_ status: String) -> String {
    let normalized = status.lowercased()
    if normalized.contains("needs_review") || normalized.contains("needs review") {
        return "Needs Review"
    }
    if normalized.contains("approved") {
        return "Approved"
    }
    if normalized.contains("reject") {
        return "Revision Needed"
    }
    if normalized.contains("green") {
        return "Ready"
    }
    if normalized.contains("yellow") {
        return "Needs Attention"
    }
    if normalized.contains("red") || normalized.contains("blocked") {
        return "Blocked"
    }
    return displayStatus(status)
}

func shortText(_ text: String, limit: Int = 120) -> String {
    guard text.count > limit else { return text }
    let index = text.index(text.startIndex, offsetBy: limit)
    return String(text[..<index]) + "..."
}

func parseDate(_ raw: String?) -> Date? {
    guard let raw, !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        return nil
    }
    let parser = ISO8601DateFormatter()
    parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = parser.date(from: raw) {
        return date
    }
    let fallback = ISO8601DateFormatter()
    fallback.formatOptions = [.withInternetDateTime]
    return fallback.date(from: raw)
}

func displayDateTime(_ raw: String?) -> String {
    guard let raw, !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        return "Unknown"
    }
    let date = parseDate(raw)
    guard let date else { return raw }
    let formatter = DateFormatter()
    formatter.dateStyle = .medium
    formatter.timeStyle = .short
    return formatter.string(from: date)
}

func compactDateTime(_ raw: String?) -> String {
    guard let date = parseDate(raw) else { return "Unknown" }
    let formatter = DateFormatter()
    formatter.dateFormat = "MMM d, h:mm a"
    return formatter.string(from: date)
}

func statusColor(_ status: String) -> Color {
    let normalized = status.lowercased()
    if normalized.contains("ready") || normalized.contains("succeeded") || normalized.contains("approved") || normalized.contains("running") {
        return .green
    }
    if normalized.contains("blocked") || normalized.contains("failed") || normalized.contains("missing") || normalized.contains("reject") {
        return .red
    }
    if normalized.contains("degraded") || normalized.contains("review") || normalized.contains("pending") {
        return .orange
    }
    return .secondary
}

func readSmallTextFile(_ path: String, maxLength: Int = 2_000) -> String {
    guard !path.isEmpty, let data = FileManager.default.contents(atPath: path) else {
        return "File not found."
    }
    let text = String(data: data, encoding: .utf8) ?? "Unable to decode file."
    if text.count <= maxLength { return text }
    let index = text.index(text.startIndex, offsetBy: maxLength)
    return String(text[..<index]) + "\n..."
}
