import Foundation
import SwiftUI

enum AppSection: String, CaseIterable, Identifiable {
    case dashboard
    case campaignGate
    case sourceManager
    case clipIndex
    case nominations
    case renderQueue
    case reviewKits
    case agents
    case readiness
    case auditLog
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .dashboard: "Dashboard"
        case .campaignGate: "Campaigns"
        case .sourceManager: "Sources"
        case .clipIndex: "Clip Index"
        case .nominations: "Nominations"
        case .renderQueue: "Render Queue"
        case .reviewKits: "Review Kits"
        case .agents: "Agents / Jobs"
        case .readiness: "Readiness"
        case .auditLog: "Audit Log"
        case .settings: "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .dashboard: "gauge.with.dots.needle.bottom.50percent"
        case .campaignGate: "checklist.checked"
        case .sourceManager: "antenna.radiowaves.left.and.right"
        case .clipIndex: "film.stack"
        case .nominations: "sparkles.tv"
        case .renderQueue: "progress.indicator"
        case .reviewKits: "play.rectangle"
        case .agents: "person.2.wave.2"
        case .readiness: "checkmark.seal"
        case .auditLog: "list.bullet.clipboard"
        case .settings: "gearshape"
        }
    }

    var accessibilityID: String {
        "section-\(rawValue)"
    }

    static let operatorSections: [AppSection] = [.dashboard, .reviewKits, .campaignGate, .readiness]
    static let agentSections: [AppSection] = [.sourceManager, .clipIndex, .nominations, .renderQueue, .agents, .auditLog]
}

struct HealthResponse: Codable {
    var apiVersion: String?
    var status: String
    var localDemoStatus: String?
    var campaignStatus: String?
    var productionGreen: Bool?
    var appSupport: String
    var renderRoot: String
    var checks: [String: HealthCheck]
    var blockers: [String]
    var discord: DiscordState
    var safety: SafetyState

    enum CodingKeys: String, CodingKey {
        case apiVersion = "api_version"
        case status
        case localDemoStatus = "local_demo_status"
        case campaignStatus = "campaign_status"
        case productionGreen = "production_green"
        case appSupport = "app_support"
        case renderRoot = "render_root"
        case checks
        case blockers
        case discord
        case safety
    }
}

struct HealthCheck: Codable, Identifiable {
    var id = UUID()
    var ok: Bool
    var detail: String

    enum CodingKeys: String, CodingKey {
        case ok
        case detail
    }
}

struct DiscordState: Codable {
    var configured: Bool
    var gatewayRunning: Bool
    var category: String
    var requiredChannels: [String]
    var missingChannels: [String]
    var channelLimit: Int
    var notes: String

    enum CodingKeys: String, CodingKey {
        case configured
        case gatewayRunning = "gateway_running"
        case category
        case requiredChannels = "required_channels"
        case missingChannels = "missing_channels"
        case channelLimit = "channel_limit"
        case notes
    }
}

struct SafetyState: Codable {
    var autopublish: String
    var payoutSubmission: String
    var accountConnection: String
    var accountRebrand: String
    var readyToPostRequiresPreview: Bool

    enum CodingKeys: String, CodingKey {
        case autopublish
        case payoutSubmission = "payout_submission"
        case accountConnection = "account_connection"
        case accountRebrand = "account_rebrand"
        case readyToPostRequiresPreview = "ready_to_post_requires_preview"
    }
}

struct SummaryResponse: Codable {
    var counts: Counts
    var campaignGate: CampaignGate
    var latestJobs: [JobRun]
    var latestAudit: [AuditEvent]

    enum CodingKeys: String, CodingKey {
        case counts
        case campaignGate = "campaign_gate"
        case latestJobs = "latest_jobs"
        case latestAudit = "latest_audit"
    }
}

struct Counts: Codable {
    var clips: Int
    var transcripts: Int
    var nominations: Int
    var reviewKits: Int
    var approvalsNeeded: Int
    var blockedJobs: Int

    enum CodingKeys: String, CodingKey {
        case clips
        case transcripts
        case nominations
        case reviewKits = "review_kits"
        case approvalsNeeded = "approvals_needed"
        case blockedJobs = "blocked_jobs"
    }
}

struct CampaignGate: Codable, Identifiable {
    var id: String
    var status: String
    var startedAt: String
    var finishedAt: String?
    var visibleCampaignCount: Int
    var selectedFeederCount: Int
    var blocker: String
    var notes: String

    enum CodingKeys: String, CodingKey {
        case id
        case status
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case visibleCampaignCount = "visible_campaign_count"
        case selectedFeederCount = "selected_feeder_count"
        case blocker
        case notes
    }
}

struct CampaignEvidence: Codable, Identifiable {
    var id: String
    var campaignID: String
    var evidenceType: String
    var title: String
    var sourceURL: String
    var screenshotPath: String
    var extractedText: String
    var capturedBy: String
    var confidence: Double
    var notes: String
    var capturedAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case campaignID = "campaign_id"
        case evidenceType = "evidence_type"
        case title
        case sourceURL = "source_url"
        case screenshotPath = "screenshot_path"
        case extractedText = "extracted_text"
        case capturedBy = "captured_by"
        case confidence
        case notes
        case capturedAt = "captured_at"
    }
}

struct SourceRoute: Codable, Identifiable {
    var id: String
    var platform: String
    var creatorHandle: String
    var sourceURL: String
    var routeType: String
    var authState: String
    var availabilityStatus: String
    var latestCheckID: String
    var notes: String
    var updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case platform
        case creatorHandle = "creator_handle"
        case sourceURL = "source_url"
        case routeType = "route_type"
        case authState = "auth_state"
        case availabilityStatus = "availability_status"
        case latestCheckID = "latest_check_id"
        case notes
        case updatedAt = "updated_at"
    }
}

struct PlatformAPICheck: Codable, Identifiable {
    var id: String
    var provider: String
    var endpoint: String
    var status: String
    var httpStatus: Int
    var requestSummary: String
    var responseExcerpt: String
    var rateLimitRemaining: String
    var error: String
    var createdAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case provider
        case endpoint
        case status
        case httpStatus = "http_status"
        case requestSummary = "request_summary"
        case responseExcerpt = "response_excerpt"
        case rateLimitRemaining = "rate_limit_remaining"
        case error
        case createdAt = "created_at"
    }
}

struct PlatformState: Codable {
    var checks: [PlatformAPICheck]
    var routes: [SourceRoute]
}

struct ReadinessReport: Codable {
    var generatedAt: String
    var overall: String
    var milestones: [String: ReadinessMilestone]
    var features: [ReadinessFeature]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case overall
        case milestones
        case features
    }
}

struct ReadinessMilestone: Codable {
    var status: String
    var ready: Bool
    var blockers: [String]
}

struct ReadinessFeature: Codable, Identifiable {
    var id: String { name }
    var name: String
    var status: String
    var evidence: String
    var blocker: String
}

struct GenericJSONResponse: Decodable {}

struct WorkspaceProfile: Codable {
    var name: String
    var customerID: String
    var licenseMode: String
    var billingEnabled: Bool
    var diagnosticsExportEnabled: Bool
    var notes: String

    enum CodingKeys: String, CodingKey {
        case name
        case customerID = "customer_id"
        case licenseMode = "license_mode"
        case billingEnabled = "billing_enabled"
        case diagnosticsExportEnabled = "diagnostics_export_enabled"
        case notes
    }
}

struct DiagnosticsExport: Codable {
    var status: String
    var path: String
    var files: [String]
}

struct ClipCandidate: Codable, Identifiable {
    var id: String
    var sourcePlatform: String
    var sourceURL: String
    var title: String
    var duration: Double
    var viewCount: Int
    var localMediaPath: String
    var provenance: String
    var discoveredAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case sourcePlatform = "source_platform"
        case sourceURL = "source_url"
        case title
        case duration
        case viewCount = "view_count"
        case localMediaPath = "local_media_path"
        case provenance
        case discoveredAt = "discovered_at"
    }
}

struct RenderNomination: Codable, Identifiable {
    var id: String
    var nominationType: String
    var scoreReason: String
    var targetStyle: String
    var status: String
    var createdAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case nominationType = "nomination_type"
        case scoreReason = "score_reason"
        case targetStyle = "target_style"
        case status
        case createdAt = "created_at"
    }
}

struct RenderKit: Codable, Identifiable {
    var id: String
    var nominationID: String
    var title: String
    var reviewVideoPath: String
    var captionPath: String
    var transcriptPath: String
    var checklistPath: String
    var sourcePath: String
    var riskPath: String
    var reviewStatus: String
    var approvedBy: String
    var approvedAt: String
    var rejectionNotes: String
    var isDemo: Int
    var createdAt: String
    var renderedAt: String?
    var clipID: String?
    var clipSourceURL: String?
    var clipSourcePlatform: String?
    var clipCreatedAt: String?
    var clipDiscoveredAt: String?
    var clipViewCount: Int?
    var clipDuration: Double?

    var isDemoKit: Bool { isDemo == 1 }
    var videoURL: URL? {
        FileManager.default.fileExists(atPath: reviewVideoPath) ? URL(fileURLWithPath: reviewVideoPath) : nil
    }

    enum CodingKeys: String, CodingKey {
        case id
        case nominationID = "nomination_id"
        case title
        case reviewVideoPath = "review_video_path"
        case captionPath = "caption_path"
        case transcriptPath = "transcript_path"
        case checklistPath = "checklist_path"
        case sourcePath = "source_path"
        case riskPath = "risk_path"
        case reviewStatus = "review_status"
        case approvedBy = "approved_by"
        case approvedAt = "approved_at"
        case rejectionNotes = "rejection_notes"
        case isDemo = "is_demo"
        case createdAt = "created_at"
        case renderedAt = "rendered_at"
        case clipID = "clip_id"
        case clipSourceURL = "clip_source_url"
        case clipSourcePlatform = "clip_source_platform"
        case clipCreatedAt = "clip_created_at"
        case clipDiscoveredAt = "clip_discovered_at"
        case clipViewCount = "clip_view_count"
        case clipDuration = "clip_duration"
    }
}

struct JobRun: Codable, Identifiable {
    var id: String
    var name: String
    var kind: String
    var status: String
    var stage: String
    var progress: Int
    var logs: String
    var outputPath: String
    var error: String
    var startedAt: String
    var finishedAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case kind
        case status
        case stage
        case progress
        case logs
        case outputPath = "output_path"
        case error
        case startedAt = "started_at"
        case finishedAt = "finished_at"
    }
}

struct AuditEvent: Codable, Identifiable {
    var id: String
    var actor: String
    var action: String
    var targetType: String
    var targetID: String
    var result: String
    var timestamp: String
    var sourceContext: String

    enum CodingKeys: String, CodingKey {
        case id
        case actor
        case action
        case targetType = "target_type"
        case targetID = "target_id"
        case result
        case timestamp
        case sourceContext = "source_context"
    }
}

struct AgentsResponse: Codable {
    var profiles: [AgentProfile]
    var schedules: [String]
    var hermesAvailable: Bool
    var gatewayRunning: Bool

    enum CodingKeys: String, CodingKey {
        case profiles
        case schedules
        case hermesAvailable = "hermes_available"
        case gatewayRunning = "gateway_running"
    }
}

struct AgentProfile: Codable, Identifiable {
    var id: String { name }
    var name: String
    var role: String
    var status: String
    var canWrite: String
    var cannotDo: String

    enum CodingKeys: String, CodingKey {
        case name
        case role
        case status
        case canWrite = "can_write"
        case cannotDo = "cannot_do"
    }
}

struct DemoRenderResponse: Codable {
    var status: String
    var created: [DemoCreatedKit]
    var blocker: String?
}

struct DemoCreatedKit: Codable, Identifiable {
    var id: String { kitID }
    var kitID: String
    var title: String
    var reviewVideoPath: String

    enum CodingKeys: String, CodingKey {
        case kitID = "kit_id"
        case title
        case reviewVideoPath = "review_video_path"
    }
}
