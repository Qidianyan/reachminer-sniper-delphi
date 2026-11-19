import { readFileSync } from "node:fs";
import type { Market } from "@gensyn-ai/gensyn-delphi-sdk";
import {
  computeCanonicalPacketDigest,
  normalizeSdkMarket,
  type PacketDigestInput,
} from "./delphiGateway.js";
import { SingleWalletGuard } from "./singleWalletGuard.js";

interface CliCommand {
  action: "verify_and_digest" | "normalize_markets";
  delphiWallet?: string;
  apiBoundWallet?: string;
  dorahacksWallet?: string;
  packet?: PacketDigestInput;
  markets?: Market[];
}

function runCli(): void {
  const rawInput = readFileSync(0, "utf8").trim();
  if (!rawInput) {
    throw new Error("Expected JSON payload on stdin");
  }
  const cmd = JSON.parse(rawInput) as CliCommand;

  if (cmd.action === "verify_and_digest") {
    const guard = SingleWalletGuard.verifyAndLock(
      cmd.delphiWallet ?? "",
      cmd.apiBoundWallet ?? "",
      cmd.dorahacksWallet ?? ""
    );
    if (!cmd.packet) {
      throw new Error("Missing packet field for verify_and_digest");
    }
    if (cmd.packet.walletAddress !== guard.canonicalAddress) {
      throw new Error(
        `Packet wallet ${cmd.packet.walletAddress} != canonical ${guard.canonicalAddress}`
      );
    }
    const digest = computeCanonicalPacketDigest(cmd.packet);
    process.stdout.write(
      JSON.stringify({
        verified: true,
        canonicalAddress: guard.canonicalAddress,
        sha256Hex: digest.sha256Hex,
        keccak256Hex: digest.keccak256Hex,
      }) + "\n"
    );
    return;
  }

  if (cmd.action === "normalize_markets") {
    const normalized = (cmd.markets ?? []).map(normalizeSdkMarket);
    process.stdout.write(JSON.stringify({ markets: normalized }) + "\n");
    return;
  }

  throw new Error(`Unsupported action: ${(cmd as { action: string }).action}`);
}

runCli();
