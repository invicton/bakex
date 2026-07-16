/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./statim/templates/**/*.html",
    "./statim/**/*.py"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      colors: {
        brand: { 400: '#22d3ee', 500: '#06b6d4', 600: '#0891b2', 700: '#0e7490' }
      }
    }
  },
  plugins: [],
}
