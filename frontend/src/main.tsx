import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/host-grotesk";
import { httpBackend } from "./api";
import { App } from "./App";
import { staticBackend } from "./staticBackend";
import "./styles.css";

// `vite build --mode static` is the public demo: the SYNTHETIC inbox, actions in the browser only.
const backend = import.meta.env.MODE === "static" ? staticBackend : httpBackend;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App backend={backend} />
  </StrictMode>,
);
