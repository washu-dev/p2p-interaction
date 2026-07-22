import type { Configuration } from "@azure/msal-browser";

export const CLIENT_ID = "cce825ec-e1df-4308-b84f-2cb0d2eb6550";
export const TENANT_ID = "4ccca3b5-71cd-4e6d-974b-4d9beb96c6d6";
// Custom scope exposed on our OWN app (Entra → Expose an API). Requesting this
// yields a token whose audience is our app, which the backend can validate — a
// Microsoft Graph (User.Read) token cannot be signature-verified by third parties.
export const API_SCOPE = "api://cce825ec-e1df-4308-b84f-2cb0d2eb6550/access_as_user";

export const msalConfig: Configuration = {
  auth: {
    clientId: CLIENT_ID,
    authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    redirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "sessionStorage",
  },
};

export const loginRequest = {
  scopes: [API_SCOPE],
};
