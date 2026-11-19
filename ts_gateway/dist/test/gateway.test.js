import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { DelphiEvidenceGateway, SingleWalletGuard, SybilWalletViolationError, computeCanonicalPacketDigest, normalizeSdkMarket, } from "../index.js";
const VALID_EIP55 = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed";
const SECOND_EIP55 = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359";
describe("SingleWalletGuard & Official @gensyn-ai/gensyn-delphi-sdk Gateway", () => {
    it("normalizes lowercase EVM address to EIP-55 and enforces 3-way identity", () => {
        const guard = SingleWalletGuard.verifyAndLock(VALID_EIP55.toLowerCase(), VALID_EIP55, VALID_EIP55.toUpperCase());
        assert.equal(guard.canonicalAddress, VALID_EIP55);
    });
    it("rejects mismatched DoraHacks / API / Delphi wallets immediately (Anti-Sybil)", () => {
        assert.throws(() => SingleWalletGuard.verifyAndLock(VALID_EIP55, VALID_EIP55, SECOND_EIP55), SybilWalletViolationError);
    });
    it("rejects zero address and corrupted mixed-case EIP-55 checksum", () => {
        assert.throws(() => SingleWalletGuard.verifyAndLock("0x0000000000000000000000000000000000000000", "0x0000000000000000000000000000000000000000", "0x0000000000000000000000000000000000000000"), SybilWalletViolationError);
        const corruptedMixed = "0x5aaeb6053F3E94C9b9A09f33669435E7Ef1BeAed";
        assert.throws(() => SingleWalletGuard.verifyAndLock(corruptedMixed, corruptedMixed, corruptedMixed), SybilWalletViolationError);
    });
    it("normalizes @gensyn-ai/gensyn-delphi-sdk Market schema accurately", () => {
        const sdkMarket = {
            id: "0x097599c9D966fF496284b892A8F13BF885b258ef",
            appMarketId: "mkt_gensyn_rlswarm_v08",
            marketUrl: "https://agent-competition.gensyn.ai/market/mkt_gensyn_rlswarm_v08",
            status: "open",
            category: "open_source_release",
            deployer: VALID_EIP55,
            implementation: SECOND_EIP55,
            metadataUri: "ipfs://bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
            metadataUriContentHash: "0x1234",
            metadata: {
                question: "Will gensyn-ai/rl-swarm ship v0.8.0 before 2026-12-06 UTC?",
                outcomes: ["Yes", "No"],
                initial_liquidity: "140",
            },
            dataSources: [],
            createdAt: "2026-11-23T00:00:00Z",
            fetchedAt: "2026-11-24T00:00:00Z",
            fetchResponseStatus: "200",
            resolvesAt: "2026-12-05T18:00:00Z",
            settledAt: null,
            settlesAt: "2026-12-06T00:00:00Z",
            winningOutcomeIdx: null,
            tradingFee: "0.01",
            proof: null,
            error: null,
            verifiable: true,
            spotPrices: [0.46, 0.54],
            spotImpliedProbabilities: [0.46, 0.54],
        };
        const norm = normalizeSdkMarket(sdkMarket);
        assert.equal(norm.marketId, "mkt_gensyn_rlswarm_v08");
        assert.equal(norm.currentProbability, 0.46);
        assert.equal(norm.resolutionTimeUtc, "2026-12-06T00:00:00Z");
        assert.equal(norm.liquidityBetaBase, 140);
    });
    it("enforces <= 3 supporting files and sends X-Delphi-Mode: competition header", async () => {
        const guard = SingleWalletGuard.verifyAndLock(VALID_EIP55, VALID_EIP55, VALID_EIP55);
        const gateway = new DelphiEvidenceGateway({
            walletGuard: guard,
            apiKey: "test-ephemeral-runtime-token",
            sdkConfig: { network: "competition-testnet" },
        });
        assert.throws(() => computeCanonicalPacketDigest({
            packetId: "pkt_overflow",
            marketId: "mkt_1",
            walletAddress: VALID_EIP55,
            explanatoryNote: "[2026-11-24T00:00:00Z] [Maintainers] Tag v1.0.0 | Verbatim Primary Excerpt: \"v1.0.0\"",
            sourceLinks: ["https://github.com/gensyn-ai/rl-swarm"],
            attachmentHashes: ["a1", "a2", "a3", "a4"],
        }));
        let capturedHeaders = {};
        const customFetch = async (_input, init) => {
            capturedHeaders = (init?.headers ?? {});
            return new Response(JSON.stringify({
                submissionId: "delphi_sub_001",
                verdict: "ACCEPTED",
                rationale: "Verified primary release artifact",
                officialProbabilityAfter: 0.68,
            }), { status: 200, headers: { "Content-Type": "application/json" } });
        };
        const receipt = await gateway.submitEvidencePacket({
            packetId: "pkt_valid_001",
            marketId: "mkt_gensyn_rlswarm_v08",
            walletAddress: VALID_EIP55,
            explanatoryNote: "[2026-11-24T14:12:00Z] [Gensyn Core] Merged PR #412 | Verbatim Primary Excerpt: \"PR #412 merged\"",
            sourceLinks: ["https://github.com/gensyn-ai/rl-swarm/pull/412"],
            attachments: [
                {
                    filename: "01_primary_source_snapshot.md",
                    mediaType: "text/markdown",
                    contentText: "# Snapshot",
                    sha256Hex: "1111111111111111111111111111111111111111111111111111111111111111",
                },
            ],
        }, customFetch);
        assert.equal(receipt.verdict, "ACCEPTED");
        assert.equal(capturedHeaders["X-Delphi-Mode"], "competition");
        assert.equal(capturedHeaders["X-Submitter-Wallet"], VALID_EIP55);
        assert.ok(receipt.packetKeccak256.startsWith("0x"));
    });
});
