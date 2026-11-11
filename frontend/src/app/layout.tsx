import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Traffic Lab | IISc QUEST",
  description: "Explore deterministic traffic simulation scenarios and compare outcomes.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
