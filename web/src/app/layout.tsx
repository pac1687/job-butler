import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job Butler — Hybrid Cloud-Edge Job Intelligence Engine",
  description:
    "Autonomous, privacy-preserving job discovery, vector scoring, and guardrail-enforced Typst resume tailoring.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased">
        {children}
      </body>
    </html>
  );
}

