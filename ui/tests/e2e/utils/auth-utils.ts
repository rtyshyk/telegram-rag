import jwt from "jsonwebtoken";

/**
 * Generate a valid JWT token for testing
 */
export function generateTestToken(
  username: string = "admin",
  secret: string = "testsecret".repeat(2),
  expiresIn: string = "24h",
): string {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    sub: username,
    iat: now,
    exp: now + 24 * 60 * 60, // 24 hours
  };
  return jwt.sign(payload, secret, { algorithm: "HS256" });
}
