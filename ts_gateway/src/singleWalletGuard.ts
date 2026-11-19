import { getAddress, type Address } from "viem";

const ZERO_ADDRESS = "0x0000000000000000000000000000000000000000";

export class SybilWalletViolationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SybilWalletViolationError";
  }
}

export interface WalletIdentityLock {
  readonly canonicalAddress: Address;
  readonly delphiWallet: Address;
  readonly apiBoundWallet: Address;
  readonly dorahacksWallet: Address;
}

export function normalizeStrictEip55(rawAddress: string, label: string): Address {
  const trimmed = (rawAddress ?? "").trim();
  if (!/^0[xX][0-9a-fA-F]{40}$/.test(trimmed)) {
    throw new SybilWalletViolationError(`Invalid EVM hex address for ${label}: "${rawAddress}"`);
  }
  const normalizedPrefix = `0x${trimmed.slice(2)}`;
  const body = normalizedPrefix.slice(2);
  const hasMixedCase = body !== body.toLowerCase() && body !== body.toUpperCase();
  const checksummed = getAddress(`0x${body.toLowerCase()}`);
  if (hasMixedCase && normalizedPrefix !== checksummed) {
    throw new SybilWalletViolationError(
      `Strict EIP-55 checksum mismatch for ${label}: got ${trimmed}, expected ${checksummed}`
    );
  }
  if (checksummed === ZERO_ADDRESS) {
    throw new SybilWalletViolationError(`Zero address is forbidden for ${label}`);
  }
  return checksummed;
}

export class SingleWalletGuard {
  public readonly canonicalAddress: Address;
  public readonly delphiWallet: Address;
  public readonly apiBoundWallet: Address;
  public readonly dorahacksWallet: Address;

  private constructor(lock: WalletIdentityLock) {
    this.canonicalAddress = lock.canonicalAddress;
    this.delphiWallet = lock.delphiWallet;
    this.apiBoundWallet = lock.apiBoundWallet;
    this.dorahacksWallet = lock.dorahacksWallet;
  }

  public static verifyAndLock(
    delphiWallet: string,
    apiBoundWallet: string,
    dorahacksWallet: string
  ): SingleWalletGuard {
    const addrDelphi = normalizeStrictEip55(delphiWallet, "delphiWallet");
    const addrApi = normalizeStrictEip55(apiBoundWallet, "apiBoundWallet");
    const addrDora = normalizeStrictEip55(dorahacksWallet, "dorahacksWallet");

    if (addrDelphi !== addrApi || addrDelphi !== addrDora) {
      throw new SybilWalletViolationError(
        `Anti-Sybil hard lock violated: delphi=${addrDelphi}, api=${addrApi}, dorahacks=${addrDora}`
      );
    }

    return new SingleWalletGuard({
      canonicalAddress: addrDelphi,
      delphiWallet: addrDelphi,
      apiBoundWallet: addrApi,
      dorahacksWallet: addrDora,
    });
  }
}
