import "./globals.css";

export const metadata = {
  title: "UP Booth Intelligence — Uttar Pradesh Elections Dashboard",
  description: "Polling-booth election analytics for Uttar Pradesh",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
