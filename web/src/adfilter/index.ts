// Entry point of the ad filter script, injected into YouTube Music's main
// world at document creation when ad blocking is on.
import { installAdFilter } from "./playerAds";

installAdFilter(globalThis);
