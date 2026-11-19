import { type Address } from "viem";
export declare class SybilWalletViolationError extends Error {
    constructor(message: string);
}
export interface WalletIdentityLock {
    readonly canonicalAddress: Address;
    readonly delphiWallet: Address;
    readonly apiBoundWallet: Address;
    readonly dorahacksWallet: Address;
}
export declare function normalizeStrictEip55(rawAddress: string, label: string): Address;
export declare class SingleWalletGuard {
    readonly canonicalAddress: Address;
    readonly delphiWallet: Address;
    readonly apiBoundWallet: Address;
    readonly dorahacksWallet: Address;
    private constructor();
    static verifyAndLock(delphiWallet: string, apiBoundWallet: string, dorahacksWallet: string): SingleWalletGuard;
}
