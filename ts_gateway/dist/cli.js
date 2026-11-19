import { readFileSync } from "node:fs";
import { computeCanonicalPacketDigest, normalizeSdkMarket, } from "./delphiGateway.js";
import { SingleWalletGuard } from "./singleWalletGuard.js";
function runCli() {
    const rawInput = readFileSync(0, "utf8").trim();
    if (!rawInput) {
        throw new Error("Expected JSON payload on stdin");
    }
    const cmd = JSON.parse(rawInput);
    if (cmd.action === "verify_and_digest") {
        const guard = SingleWalletGuard.verifyAndLock(cmd.delphiWallet ?? "", cmd.apiBoundWallet ?? "", cmd.dorahacksWallet ?? "");
        if (!cmd.packet) {
            throw new Error("Missing packet field for verify_and_digest");
        }
        if (cmd.packet.walletAddress !== guard.canonicalAddress) {
            throw new Error(`Packet wallet ${cmd.packet.walletAddress} != canonical ${guard.canonicalAddress}`);
        }
        const digest = computeCanonicalPacketDigest(cmd.packet);
        process.stdout.write(JSON.stringify({
            verified: true,
            canonicalAddress: guard.canonicalAddress,
            sha256Hex: digest.sha256Hex,
            keccak256Hex: digest.keccak256Hex,
        }) + "\n");
        return;
    }
    if (cmd.action === "normalize_markets") {
        const normalized = (cmd.markets ?? []).map(normalizeSdkMarket);
        process.stdout.write(JSON.stringify({ markets: normalized }) + "\n");
        return;
    }
    throw new Error(`Unsupported action: ${cmd.action}`);
}
runCli();
