import { dashboardApi } from "@/api/dashboard-api";
import { getBrandLogoUrl } from "@/lib/brand-assets";
import type {
  AuthSuccessResponse,
  OnchainCreditPaymentIntent,
  OnchainPaymentVerifyResponse,
  WalletAuthSource,
} from "@/types/api";

const BASE_CHAIN_ID_HEX = "0x2105";
const USDC_TRANSFER_SELECTOR = "0xa9059cbb";
const BASE_CHAIN_PARAMS = {
  chainId: BASE_CHAIN_ID_HEX,
  chainName: "Base",
  nativeCurrency: {
    name: "Ether",
    symbol: "ETH",
    decimals: 18,
  },
  rpcUrls: ["https://mainnet.base.org"],
  blockExplorerUrls: ["https://basescan.org"],
};

interface EthereumProvider {
  isBaseAccount?: boolean;
  isCoinbaseWallet?: boolean;
  isOkxWallet?: boolean;
  providers?: EthereumProvider[];
  request<T = unknown>(args: { method: string; params?: unknown[] }): Promise<T>;
}

declare global {
  interface Window {
    ethereum?: EthereumProvider;
    okxwallet?: EthereumProvider;
  }
}

function providerErrorMessage(error: unknown) {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message?: unknown }).message || "");
  }
  return "";
}

function providerErrorCode(error: unknown) {
  if (error && typeof error === "object" && "code" in error) {
    return Number((error as { code?: unknown }).code || 0);
  }
  return 0;
}

let baseAccountProvider: EthereumProvider | null = null;

export function walletSourceLabel(source: WalletAuthSource) {
  if (source === "base_wallet") return "Base Account";
  if (source === "okx_wallet") return "OKX Wallet";
  return "Wallet";
}

async function resolveBaseAccountProvider() {
  if (baseAccountProvider) return baseAccountProvider;
  const { createBaseAccountSDK } = await import("@base-org/account");
  const sdk = createBaseAccountSDK({
    appName: "Virtuals Whale Radar",
    appLogoUrl: getBrandLogoUrl(),
    appChainIds: [8453],
  });
  baseAccountProvider = sdk.getProvider() as EthereumProvider;
  return baseAccountProvider;
}

function resolveInjectedProvider(predicate?: (provider: EthereumProvider) => boolean) {
  const provider = window.ethereum;
  if (!provider) {
    return null;
  }
  if (predicate) {
    return provider.providers?.find(predicate) ?? (predicate(provider) ? provider : null);
  }
  return provider.providers?.[0] ?? provider;
}

async function resolveOkxWalletProvider() {
  const okxProvider =
    window.okxwallet ??
    resolveInjectedProvider((item) => Boolean(item.isOkxWallet));
  if (!okxProvider) {
    throw new Error("没有检测到 OKX Wallet，请在欧易钱包浏览器或已安装 OKX Wallet 插件的浏览器中打开。");
  }
  return okxProvider;
}

async function resolveWalletProvider(source: WalletAuthSource) {
  if (source === "base_wallet") {
    return resolveBaseAccountProvider();
  }
  if (source === "okx_wallet") {
    return resolveOkxWalletProvider();
  }
  const provider = resolveInjectedProvider();
  if (!provider) {
    throw new Error("没有检测到可用的钱包，请在已安装钱包的浏览器中打开。");
  }
  return provider;
}

export async function switchToBase(provider: EthereumProvider) {
  const chainId = await provider
    .request<string>({ method: "eth_chainId" })
    .catch(() => "");
  if (String(chainId).toLowerCase() === BASE_CHAIN_ID_HEX) return;

  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: BASE_CHAIN_ID_HEX }],
    });
  } catch (error) {
    if (providerErrorCode(error) !== 4902) {
      throw new Error(providerErrorMessage(error) || "请先切换到 Base Mainnet。");
    }
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [BASE_CHAIN_PARAMS],
    });
  }
}

export async function requestWalletAddress(provider: EthereumProvider) {
  const accounts = await provider.request<string[]>({ method: "eth_requestAccounts" });
  const address = String(accounts?.[0] || "").trim();
  if (!/^0x[a-fA-F0-9]{40}$/.test(address)) {
    throw new Error("没有获取到有效的钱包地址。");
  }
  return address;
}

export async function signInWithWallet(source: WalletAuthSource): Promise<AuthSuccessResponse> {
  const provider = await resolveWalletProvider(source);
  const wallet = await requestWalletAddress(provider);
  await switchToBase(provider);
  const challenge = await dashboardApi.auth.walletChallenge(wallet, source);
  const signature = await provider.request<string>({
    method: "personal_sign",
    params: [challenge.message, wallet],
  });
  return dashboardApi.auth.walletVerify({
    wallet,
    source,
    nonce: challenge.nonce,
    message: challenge.message,
    signature,
  });
}

export async function signInWithBaseWallet(): Promise<AuthSuccessResponse> {
  return signInWithWallet("base_wallet");
}

export async function signInWithOkxWallet(): Promise<AuthSuccessResponse> {
  return signInWithWallet("okx_wallet");
}

function stripHexPrefix(value: string) {
  return value.startsWith("0x") ? value.slice(2) : value;
}

function padHexWord(value: string) {
  const raw = stripHexPrefix(value).toLowerCase();
  if (raw.length > 64) {
    throw new Error("ERC20 参数过长。");
  }
  return raw.padStart(64, "0");
}

export function encodeUsdcTransfer(receiver: string, amountRaw: string) {
  if (!/^0x[a-fA-F0-9]{40}$/.test(receiver)) {
    throw new Error("USDC 收款地址无效。");
  }
  const amount = BigInt(amountRaw);
  if (amount <= 0n) {
    throw new Error("USDC 支付金额无效。");
  }
  return `${USDC_TRANSFER_SELECTOR}${padHexWord(receiver)}${padHexWord(amount.toString(16))}`;
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isReceiptPendingError(error: unknown) {
  const message = error instanceof Error ? error.message.toLowerCase() : String(error || "").toLowerCase();
  return message.includes("receipt") && (message.includes("not found") || message.includes("confirmation"));
}

export async function payOnchainCreditWithWallet(
  planId: string,
  source: WalletAuthSource,
): Promise<OnchainPaymentVerifyResponse> {
  const provider = await resolveWalletProvider(source);
  const wallet = await requestWalletAddress(provider);
  await switchToBase(provider);
  const intentResponse = await dashboardApi.app.createOnchainPaymentIntent({
    plan_id: planId,
    payer_wallet: wallet,
  });
  const intent: OnchainCreditPaymentIntent = intentResponse.item;
  const txHash = await provider.request<string>({
    method: "eth_sendTransaction",
    params: [
      {
        from: wallet,
        to: intent.token_addr,
        value: "0x0",
        data: encodeUsdcTransfer(intent.receiver, intent.amount_raw),
      },
    ],
  });
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      return await dashboardApi.app.verifyOnchainPaymentIntent(intent.id, txHash, attempt === 0 ? 90 : 60);
    } catch (error) {
      if (!isReceiptPendingError(error)) {
        throw error;
      }
      if (attempt >= 3) {
        throw new Error("Base 交易已提交，但链上回执仍未返回。请稍后在链上支付记录里重新确认。");
      }
      await delay(5000);
    }
  }
  throw new Error("Base 交易已提交，但链上回执仍未返回。请稍后在链上支付记录里重新确认。");
}
