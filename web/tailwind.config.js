// design-system 단일 진실원: ../design-system/tokens/tailwind.config.js (CJS)
// 본 설정은 content만 정의하고 토큰 전체를 design-system에서 가져온다.
const dsConfig = require('../design-system/tokens/tailwind.config.js');

/** @type {import('tailwindcss').Config} */
module.exports = {
  ...dsConfig,
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './api/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
};
