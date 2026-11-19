import { createHash } from "node:crypto";
import { performance } from "node:perf_hooks";
import { DelphiClient, } from "@gensyn-ai/gensyn-delphi-sdk";
import { keccak256, stringToBytes } from "viem";
export const MAX_SUPPORTING_FILES = 3;
export function computeCanonicalPacketDigest(input) {
    if (input.attachmentHashes.length > MAX_SUPPORTING_FILES) {
        throw new Error(`Delphi Evidence Mining allows <= ${MAX_SUPPORTING_FILES} supporting files, got ${input.attachmentHashes.length}`);
    }
    const canonicalPayload = JSON.stringify({
        attachmentHashes: [...input.attachmentHashes],
        explanatoryNote: input.explanatoryNote,
        marketId: input.marketId,
        packetId: input.packetId,
        sourceLinks: [...input.sourceLinks],
        walletAddress: input.walletAddress,
    });
    const sha256Hex = createHash("sha256").update(canonicalPayload, "utf8").digest("hex");
    const keccak256Hex = keccak256(stringToBytes(canonicalPayload));
    return { sha256Hex, keccak256Hex };
}
export function normalizeSdkMarket(market) {
    const impliedYes = market.spotImpliedProbabilities && market.spotImpliedProbabilities.length > 0
        ? market.spotImpliedProbabilities[0]
        : 0.5;
    const resolutionIso = market.settlesAt ?? market.resolvesAt ?? new Date(Date.now() + 86400_000).toISOString();
    const initialLiquidityRaw = Number(market.metadata?.initial_liquidity ?? "100");
    const liquidityBetaBase = Number.isFinite(initialLiquidityRaw) && initialLiquidityRaw > 0
        ? initialLiquidityRaw
        : 100.0;
    return {
        marketId: market.appMarketId || market.id,
        proxyAddress: market.id,
        question: market.metadata?.question ?? "",
        category: market.category || "general",
        status: market.status.toUpperCase(),
        currentProbability: Math.min(Math.max(impliedYes, 0.001), 0.999),
        resolutionTimeUtc: resolutionIso,
        liquidityBetaBase,
        verifiable: market.verifiable,
    };
}
export class DelphiEvidenceGateway {
    sdkClient;
    walletGuard;
    network;
    apiBaseUrl;
    apiKey;
    constructor(params) {
        this.walletGuard = params.walletGuard;
        this.network = params.sdkConfig?.network ?? "competition-testnet";
        this.apiBaseUrl =
            params.apiBaseUrl ??
                params.sdkConfig?.apiBaseUrl ??
                (this.network === "mainnet" ? "https://api.delphi.fyi/" : "https://delphi-api.gensyn.ai/");
        this.apiKey = params.apiKey ?? params.sdkConfig?.apiKey ?? process.env.DELPHI_API_ACCESS_KEY ?? "";
        this.sdkClient = new DelphiClient({
            network: this.network,
            apiBaseUrl: this.apiBaseUrl,
            apiKey: this.apiKey,
            ...params.sdkConfig,
        });
    }
    async fetchActiveCompetitionMarkets(params = {
        status: "open",
        orderBy: "settles_at",
        limit: 50,
        pricesAndImpliedProbabilities: true,
    }) {
        const resp = await this.sdkClient.listMarkets(params);
        const list = resp.markets ?? [];
        return list.map(normalizeSdkMarket);
    }
    async submitEvidencePacket(request, fetchImpl = fetch) {
        if (request.walletAddress !== this.walletGuard.canonicalAddress) {
            throw new Error(`Submitter wallet ${request.walletAddress} does not match locked wallet ${this.walletGuard.canonicalAddress}`);
        }
        if (request.attachments.length > MAX_SUPPORTING_FILES) {
            throw new Error(`Cannot attach ${request.attachments.length} files; Delphi cap is ${MAX_SUPPORTING_FILES}`);
        }
        if (request.sourceLinks.length === 0) {
            throw new Error("At least 1 authoritative source link is required");
        }
        const digest = computeCanonicalPacketDigest({
            packetId: request.packetId,
            marketId: request.marketId,
            walletAddress: request.walletAddress,
            explanatoryNote: request.explanatoryNote,
            sourceLinks: request.sourceLinks,
            attachmentHashes: request.attachments.map((a) => a.sha256Hex),
        });
        const endpointUrl = new URL(`/v1/markets/${encodeURIComponent(request.marketId)}/evidence`, this.apiBaseUrl);
        const headers = {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-API-Key": this.apiKey,
            "X-Submitter-Wallet": this.walletGuard.canonicalAddress,
            "X-Packet-Keccak256": digest.keccak256Hex,
        };
        if (this.network.startsWith("competition")) {
            headers["X-Delphi-Mode"] = "competition";
        }
        const t0 = performance.now();
        const response = await fetchImpl(endpointUrl.toString(), {
            method: "POST",
            headers,
            body: JSON.stringify({
                packetId: request.packetId,
                walletAddress: this.walletGuard.canonicalAddress,
                explanatoryNote: request.explanatoryNote,
                sourceLinks: request.sourceLinks,
                supportingFiles: request.attachments.map((att) => ({
                    filename: att.filename,
                    mediaType: att.mediaType,
                    contentBase64: Buffer.from(att.contentText, "utf8").toString("base64"),
                    sha256: att.sha256Hex,
                })),
            }),
        });
        const latencyMs = Number((performance.now() - t0).toFixed(2));
        if (!response.ok) {
            const errBody = await response.text();
            throw new Error(`Delphi Evidence API error (${response.status}): ${errBody}`);
        }
        const parsed = (await response.json());
        return {
            submissionId: parsed.submissionId,
            marketId: request.marketId,
            verdict: parsed.verdict,
            rationale: parsed.rationale,
            officialProbabilityAfter: parsed.officialProbabilityAfter,
            packetKeccak256: digest.keccak256Hex,
            latencyMs,
        };
    }
}
