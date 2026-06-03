import SwiftUI

enum PlatformUIOverlay: String, CaseIterable, Identifiable, Hashable {
    case none
    case instagram
    case tiktok
    case youtubeShorts

    var id: String { rawValue }

    var shortTitle: String {
        switch self {
        case .none: "Off"
        case .instagram: "IG"
        case .tiktok: "TT"
        case .youtubeShorts: "YT"
        }
    }

    var title: String {
        switch self {
        case .none: "No platform overlay"
        case .instagram: "Instagram Reels"
        case .tiktok: "TikTok"
        case .youtubeShorts: "YouTube Shorts"
        }
    }
}

struct PortraitReviewPreviewStage<Content: View>: View {
    private let stageHeight: CGFloat = 560
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        GeometryReader { proxy in
            let phoneSize = phoneSize(in: proxy.size)
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(.black.opacity(0.34))

                content
                    .frame(width: phoneSize.width, height: phoneSize.height)
                    .background(.black)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay {
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(.white.opacity(0.13), lineWidth: 1)
                    }
                    .shadow(color: .black.opacity(0.34), radius: 18, x: 0, y: 10)
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .frame(height: stageHeight)
    }

    private func phoneSize(in container: CGSize) -> CGSize {
        let aspect = 9.0 / 16.0
        let maxHeight = min(container.height, stageHeight)
        let heightFitWidth = container.width / aspect
        let height = min(maxHeight, heightFitWidth)
        return CGSize(width: height * aspect, height: height)
    }
}

struct SocialPlatformChromeOverlay: View {
    var platform: PlatformUIOverlay

    var body: some View {
        ZStack {
            if let spec = PlatformSafeZoneSpec(platform: platform) {
                PlatformSafeZoneOverlay(spec: spec)
                    .transition(.opacity)
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(platform == .none)
    }
}

private struct PlatformSafeZoneSpec {
    var platform: PlatformUIOverlay
    var title: String
    var topRisk: CGFloat
    var bottomRisk: CGFloat
    var rightRisk: CGFloat
    var leftPadding: CGFloat
    var subtitleBandTop: CGFloat
    var subtitleBandHeight: CGFloat
    var accent: Color

    init?(platform: PlatformUIOverlay) {
        self.platform = platform
        switch platform {
        case .none:
            return nil
        case .instagram:
            title = "Instagram Reels"
            topRisk = 0.11
            bottomRisk = 0.23
            rightRisk = 0.15
            leftPadding = 0.04
            subtitleBandTop = 0.64
            subtitleBandHeight = 0.09
            accent = .pink
        case .tiktok:
            title = "TikTok"
            topRisk = 0.12
            bottomRisk = 0.27
            rightRisk = 0.18
            leftPadding = 0.04
            subtitleBandTop = 0.63
            subtitleBandHeight = 0.10
            accent = .cyan
        case .youtubeShorts:
            title = "YouTube Shorts"
            topRisk = 0.09
            bottomRisk = 0.25
            rightRisk = 0.17
            leftPadding = 0.04
            subtitleBandTop = 0.63
            subtitleBandHeight = 0.10
            accent = .red
        }
    }
}

private struct PlatformSafeZoneOverlay: View {
    var spec: PlatformSafeZoneSpec

    var body: some View {
        GeometryReader { proxy in
            let size = proxy.size
            let topHeight = size.height * spec.topRisk
            let bottomHeight = size.height * spec.bottomRisk
            let rightWidth = size.width * spec.rightRisk
            let leftInset = size.width * spec.leftPadding
            let safeTop = size.height * spec.subtitleBandTop
            let safeHeight = size.height * spec.subtitleBandHeight
            let safeWidth = size.width - leftInset - rightWidth - 14

            ZStack(alignment: .topLeading) {
                platformGradient

                riskBlock(
                    label: "TOP UI",
                    systemImage: topIcon,
                    color: spec.accent,
                    alignment: .top
                )
                .frame(width: size.width, height: topHeight)
                .position(x: size.width / 2, y: topHeight / 2)

                riskBlock(
                    label: "CAPTION + NAV UI",
                    systemImage: "rectangle.bottomthird.inset.filled",
                    color: .red,
                    alignment: .bottom
                )
                .frame(width: size.width, height: bottomHeight)
                .position(x: size.width / 2, y: size.height - bottomHeight / 2)

                rightRiskBlock(color: .red)
                .frame(width: rightWidth, height: size.height * 0.58)
                .position(x: size.width - rightWidth / 2, y: size.height * 0.53)

                subtitleSafeBand(width: safeWidth, height: safeHeight)
                    .position(x: leftInset + safeWidth / 2, y: safeTop + safeHeight / 2)

                platformChrome(size: size, bottomHeight: bottomHeight, rightWidth: rightWidth)
            }
            .frame(width: size.width, height: size.height)
        }
        .compositingGroup()
    }

    private var platformGradient: some View {
        LinearGradient(
            colors: [.black.opacity(0.34), .clear, .clear, .black.opacity(0.44)],
            startPoint: .top,
            endPoint: .bottom
        )
    }

    private var topIcon: String {
        switch spec.platform {
        case .none: "rectangle"
        case .instagram: "camera"
        case .tiktok: "magnifyingglass"
        case .youtubeShorts: "play.rectangle"
        }
    }

    private var rightRailIcon: String {
        switch spec.platform {
        case .none: "circle"
        case .instagram: "heart"
        case .tiktok: "heart.fill"
        case .youtubeShorts: "hand.thumbsup.fill"
        }
    }

    private func riskBlock(
        label: String,
        systemImage: String,
        color: Color,
        alignment: Alignment
    ) -> some View {
        ZStack(alignment: alignment) {
            Rectangle()
                .fill(color.opacity(0.18))
                .overlay {
                    Rectangle()
                        .stroke(color.opacity(0.56), lineWidth: 1)
                }

            Label(label, systemImage: systemImage)
                .font(.system(size: 11, weight: .black, design: .rounded))
                .foregroundStyle(.white)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(color.opacity(0.72), in: Capsule())
                .shadow(color: .black.opacity(0.8), radius: 2, x: 0, y: 1)
                .padding(8)
        }
    }

    private func subtitleSafeBand(width: CGFloat, height: CGFloat) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12)
                .fill(.green.opacity(0.10))
                .overlay {
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(style: StrokeStyle(lineWidth: 2, dash: [8, 5]))
                        .foregroundStyle(.green.opacity(0.92))
                }

            HStack(spacing: 6) {
                Image(systemName: "captions.bubble.fill")
                Text("SUBTITLE SAFE BAND")
            }
            .font(.system(size: 11, weight: .black, design: .rounded))
            .foregroundStyle(.white)
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .background(.green.opacity(0.82), in: Capsule())
            .shadow(color: .black.opacity(0.75), radius: 2, x: 0, y: 1)
        }
        .frame(width: max(width, 80), height: max(height, 36))
    }

    private func rightRiskBlock(color: Color) -> some View {
        Rectangle()
            .fill(color.opacity(0.14))
            .overlay {
                Rectangle()
                    .stroke(color.opacity(0.62), lineWidth: 1)
            }
    }

    @ViewBuilder
    private func platformChrome(size: CGSize, bottomHeight: CGFloat, rightWidth: CGFloat) -> some View {
        switch spec.platform {
        case .none:
            EmptyView()
        case .instagram:
            instagramChrome(size: size, bottomHeight: bottomHeight, rightWidth: rightWidth)
        case .tiktok:
            tiktokChrome(size: size, bottomHeight: bottomHeight, rightWidth: rightWidth)
        case .youtubeShorts:
            youtubeChrome(size: size, bottomHeight: bottomHeight, rightWidth: rightWidth)
        }
    }

    private func instagramChrome(size: CGSize, bottomHeight: CGFloat, rightWidth: CGFloat) -> some View {
        ZStack(alignment: .topLeading) {
            Text("Reels")
                .font(.system(size: scaled(20, in: size), weight: .black, design: .rounded))
                .foregroundStyle(.white)
                .shadow(color: .black, radius: 2)
                .position(x: 46, y: 36)

            rightRail(
                icons: ["heart", "message", "paperplane", "bookmark"],
                in: size,
                rightWidth: rightWidth
            )

            bottomInfoStub(in: size, bottomHeight: bottomHeight, title: "@creator  Follow")
        }
    }

    private func tiktokChrome(size: CGSize, bottomHeight: CGFloat, rightWidth: CGFloat) -> some View {
        ZStack(alignment: .topLeading) {
            HStack(spacing: 14) {
                Text("Following").opacity(0.7)
                Text("For You")
                    .overlay(alignment: .bottom) {
                        Capsule()
                            .fill(.white)
                            .frame(height: 2)
                            .offset(y: 6)
                    }
            }
            .font(.system(size: scaled(17, in: size), weight: .black, design: .rounded))
            .foregroundStyle(.white)
            .shadow(color: .black, radius: 2)
            .position(x: size.width * 0.58, y: 40)

            Image(systemName: "magnifyingglass")
                .font(.system(size: scaled(19, in: size), weight: .black))
                .foregroundStyle(.white)
                .shadow(color: .black, radius: 2)
                .position(x: size.width - 24, y: 40)

            rightRail(
                icons: ["person.crop.circle.badge.plus", "heart.fill", "message.fill", "arrowshape.turn.up.right.fill"],
                in: size,
                rightWidth: rightWidth
            )

            bottomInfoStub(in: size, bottomHeight: bottomHeight, title: "@creator")
        }
    }

    private func youtubeChrome(size: CGSize, bottomHeight: CGFloat, rightWidth: CGFloat) -> some View {
        ZStack(alignment: .topLeading) {
            Text("Shorts")
                .font(.system(size: scaled(20, in: size), weight: .black, design: .rounded))
                .foregroundStyle(.white)
                .shadow(color: .black, radius: 2)
                .position(x: 52, y: 36)

            rightRail(
                icons: ["hand.thumbsup.fill", "hand.thumbsdown", "message.fill", "arrowshape.turn.up.right.fill", "arrow.triangle.2.circlepath"],
                in: size,
                rightWidth: rightWidth
            )

            bottomInfoStub(in: size, bottomHeight: bottomHeight, title: "@creator  Subscribe")
        }
    }

    private func rightRail(icons: [String], in size: CGSize, rightWidth: CGFloat) -> some View {
        VStack(spacing: max(12, size.height * 0.028)) {
            ForEach(icons, id: \.self) { icon in
                Image(systemName: icon)
                    .font(.system(size: scaled(24, in: size), weight: .bold))
                    .frame(width: rightWidth, height: max(32, size.height * 0.044))
            }
        }
        .foregroundStyle(.white)
        .shadow(color: .black, radius: 2)
        .position(x: size.width - rightWidth / 2, y: size.height * 0.58)
    }

    private func bottomInfoStub(in size: CGSize, bottomHeight: CGFloat, title: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.system(size: scaled(13, in: size), weight: .black, design: .rounded))
            RoundedRectangle(cornerRadius: 2)
                .fill(.white.opacity(0.86))
                .frame(width: size.width * 0.42, height: 3)
            RoundedRectangle(cornerRadius: 2)
                .fill(.white.opacity(0.55))
                .frame(width: size.width * 0.34, height: 3)
        }
        .foregroundStyle(.white)
        .shadow(color: .black, radius: 2)
        .position(x: size.width * 0.28, y: size.height - bottomHeight * 0.44)
    }

    private func scaled(_ value: CGFloat, in size: CGSize) -> CGFloat {
        value * max(0.72, min(1.12, size.width / 430))
    }
}
