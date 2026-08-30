/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        "eva-green": "#3D5C2E",
        "eva-purple": "#7A5A3A",
        "eva-orange": "#C97A3A",
        "bg-dark": "#FAF6EC",
        "card-dark": "#FFFCF3",
        "text-light": "#2A241B",
        "border-dark": "#C9B38A"
      }
    }
  },
  plugins: [require("@tailwindcss/typography")]
};
