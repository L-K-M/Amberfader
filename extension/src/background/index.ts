// Event-page entry point. Everything here must register at module top level:
// Firefox may unload and restart the background page at any time, and only
// top-level listeners survive re-evaluation. Session state is rebuilt inside
// router.init() from storage.
import { Router, installRuntime } from "./router";


const router = new Router();
installRuntime(router);
void router.init();
