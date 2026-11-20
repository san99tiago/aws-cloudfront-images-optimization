import { Amplify } from "aws-amplify";
import { fetchAuthSession, getCurrentUser, signIn, signOut } from "aws-amplify/auth";

import type { AppConfig } from "./config";

export type JwtClaims = Record<string, unknown>;

export interface Session {
  idToken: string;
  idHeader: JwtClaims;
  idClaims: JwtClaims;
  accessClaims: JwtClaims;
}

export function configureAuth(config: AppConfig): void {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.userPoolId,
        userPoolClientId: config.userPoolClientId,
        loginWith: { email: true },
      },
    },
  });
}

function decodeSegment(token: string, index: number): JwtClaims {
  const segment = token.split(".")[index] ?? "";
  const base64 = segment.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(segment.length / 4) * 4, "=");
  try {
    return JSON.parse(atob(base64)) as JwtClaims;
  } catch {
    return {};
  }
}

/** SRP sign-in: the password never leaves the browser, Cognito returns the JWTs (ID, access, refresh). */
export async function login(email: string, password: string): Promise<void> {
  try {
    await signOut();
  } catch {
    // no previous session
  }
  const result = await signIn({
    username: email.trim().toLowerCase(),
    password,
    options: { authFlowType: "USER_SRP_AUTH" },
  });
  if (!result.isSignedIn) {
    throw new Error(`Cognito pide un paso adicional: ${result.nextStep.signInStep}`);
  }
}

export async function currentSession(): Promise<Session | null> {
  try {
    await getCurrentUser();
    const session = await fetchAuthSession();
    const idToken = session.tokens?.idToken;
    if (!idToken) {
      return null;
    }
    const raw = idToken.toString();
    return {
      idToken: raw,
      idHeader: decodeSegment(raw, 0),
      idClaims: idToken.payload as JwtClaims,
      accessClaims: (session.tokens?.accessToken?.payload ?? {}) as JwtClaims,
    };
  } catch {
    return null;
  }
}

export async function logout(): Promise<void> {
  await signOut();
}
