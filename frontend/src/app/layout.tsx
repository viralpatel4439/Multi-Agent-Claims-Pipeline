import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import Providers from "./providers"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Plum Claims Pipeline",
  description: "Health Insurance Claims Processing System",
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"
const BACKEND_BASE = API_BASE.replace(/\/api$/, "")

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <div className="min-h-screen bg-gray-50">
            <nav className="bg-white border-b border-gray-200 px-6 py-4">
              <div className="max-w-6xl mx-auto flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-green-600 rounded-lg flex items-center justify-center">
                    <span className="text-white font-bold text-sm">P</span>
                  </div>
                  <span className="font-semibold text-gray-900">Plum Claims</span>
                </div>
                <div className="flex gap-6 items-center">
                  <a href="/" className="text-sm text-gray-600 hover:text-gray-900 font-medium">Submit Claim</a>
                  <a href="/claims" className="text-sm text-gray-600 hover:text-gray-900 font-medium">Claims</a>
                  <a href={`${BACKEND_BASE}/api/health`} target="_blank" rel="noreferrer" className="text-sm text-gray-400 hover:text-gray-700">Health ↗</a>
                  <a href={`${BACKEND_BASE}/docs`} target="_blank" rel="noreferrer" className="text-sm text-gray-400 hover:text-gray-700">API Docs ↗</a>
                </div>
              </div>
            </nav>
            <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  )
}
