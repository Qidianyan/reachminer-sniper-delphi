import { DelphiClient, type DelphiClientConfig, type ListMarketsParams, type Market } from "@gensyn-ai/gensyn-delphi-sdk";
import { type Hex } from "viem";
import { SingleWalletGuard } from "./singleWalletGuard.js";
export declare const MAX_SUPPORTING_FILES = 3;
export interface SupportingAttachmentPayload {
    readonly filename: string;
    readonly mediaType: string;
    readonly contentText: string;
    readonly sha256Hex: string;
}
export interface SubmitEvidenceRequest {
    readonly packetId: string;
    readonly marketId: string;
    readonly walletAddress: string;
    readonly explanatoryNote: string;
    readonly sourceLinks: readonly string[];
    readonly attachments: readonly SupportingAttachmentPayload[];
}
export interface SubmitEvidenceResponse {
    readonly submissionId: string;
    readonly marketId: string;
    readonly verdict: "ACCEPTED" | "REJECTED" | "PENDING";
    readonly rationale: string;
    readonly officialProbabilityAfter?: number;
    readonly packetKeccak256: Hex;
    readonly latencyMs: number;
}
export interface NormalizedDelphiMarket {
    readonly marketId: string;
    readonly proxyAddress: string;
    readonly question: string;
    readonly category: string;
    readonly status: string;
    readonly currentProbability: number;
    readonly resolutionTimeUtc: string;
    readonly liquidityBetaBase: number;
    readonly verifiable: boolean;
}
export interface PacketDigestInput {
    readonly packetId: string;
    readonly marketId: string;
    readonly walletAddress: string;
    readonly explanatoryNote: string;
    readonly sourceLinks: readonly string[];
    readonly attachmentHashes: readonly string[];
}
export declare function computeCanonicalPacketDigest(input: PacketDigestInput): {
    sha256Hex: string;
    keccak256Hex: Hex;
};
export declare function normalizeSdkMarket(market: Market): NormalizedDelphiMarket;
export declare class DelphiEvidenceGateway {
    readonly sdkClient: DelphiClient;
    readonly walletGuard: SingleWalletGuard;
    private readonly network;
    private readonly apiBaseUrl;
    private readonly apiKey;
    constructor(params: {
        walletGuard: SingleWalletGuard;
        sdkConfig?: DelphiClientConfig;
        apiKey?: string;
        apiBaseUrl?: string;
    });
    fetchActiveCompetitionMarkets(params?: ListMarketsParams): Promise<NormalizedDelphiMarket[]>;
    submitEvidencePacket(request: SubmitEvidenceRequest, fetchImpl?: typeof fetch): Promise<SubmitEvidenceResponse>;
}
