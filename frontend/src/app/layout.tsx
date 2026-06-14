import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import Providers from "./providers"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Plum Claims Pipeline",
  description: "Health Insurance Claims Processing System",
}

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
                <div className="flex gap-4">
                  <a href="/" className="text-sm text-gray-600 hover:text-gray-900">Submit Claim</a>
                  <a href="/api/health" target="_blank" className="text-sm text-gray-600 hover:text-gray-900">Health</a>
                  <a href="/api/docs" target="_blank" className="text-sm text-gray-600 hover:text-gray-900">API Docs</a>
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
