import type { Configuration } from "@azure/msal-browser";

export const CLIENT_ID = "cce825ec-e1df-4308-b84f-2cb0d2eb6550";
export const TENANT_ID = "4ccca3b5-71cd-4e6d-974b-4d9beb96c6d6";
// User.Read is pre-consented for all org users — no custom scope needed.
export const API_SCOPE = "User.Read";

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
