import Foundation

struct BackendClient {
    var baseURL = URL(string: "http://127.0.0.1:8765/api")!

    func get<T: Decodable>(_ path: String, timeout: TimeInterval = 15) async throws -> T {
        let url = try makeURL(path)
        var request = URLRequest(url: url)
        request.timeoutInterval = timeout
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    func post<T: Decodable>(_ path: String, body: EncodableBody? = nil, timeout: TimeInterval = 30) async throws -> T {
        let url = try makeURL(path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body.value)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            let text = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw BackendError.http(status: http.statusCode, text: text)
        }
    }

    private func makeURL(_ path: String) throws -> URL {
        if path.contains("?") {
            guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else {
                throw BackendError.invalidURL(path)
            }
            return url
        }
        return baseURL.appendingPathComponent(path)
    }
}

struct EncodableBody: @unchecked Sendable {
    var value: [String: Any]
}

enum BackendError: LocalizedError {
    case http(status: Int, text: String)
    case invalidURL(String)

    var errorDescription: String? {
        switch self {
        case .http(let status, let text):
            "Backend returned HTTP \(status): \(text)"
        case .invalidURL(let path):
            "Backend path is invalid: \(path)"
        }
    }
}
