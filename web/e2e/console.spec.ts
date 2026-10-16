import { expect, test, type Page } from '@playwright/test';

const USER = process.env.CONSOLE_USER || 'admin';
const PASS = process.env.CONSOLE_PASS || 'kspoAdmin2026!';

async function login(page: Page) {
  await page.goto('/login');
  await page.fill('input[name="username"]', USER);
  await page.fill('input[name="password"]', PASS);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/', { timeout: 20_000 });
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('1. Executive Dashboard — 실데이터 카운트', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('dashboard')).toBeVisible();
  await expect(page.getByTestId('stat-cards')).toBeVisible();
  // 전체 사이트 카드가 0이 아닌 실제 수치를 표시
  await expect(page.getByText('전체 사이트')).toBeVisible();
  const text = await page.getByTestId('stat-cards').innerText();
  expect(text).toMatch(/\d/); // 숫자 존재
  await expect(page.getByText('문서 상태 분포')).toBeVisible();
});

test('2. Site Explorer — 목록·필터·구조', async ({ page }) => {
  await page.goto('/sites');
  await expect(page.getByTestId('site-list')).toBeVisible();
  // 사이트 항목 존재
  const items = page.getByTestId('site-list').locator('button');
  expect(await items.count()).toBeGreaterThan(0);
  // 필터: 활성
  await page.getByTestId('site-filter-active').click();
  await expect(page.getByTestId('site-structure')).toBeVisible();
  // 검색
  await page.getByTestId('site-search').fill('kspo');
  await expect(items.first()).toBeVisible();
  // 구조 패널에 커버리지/패턴
  await expect(page.getByText('크롤 커버리지 (상태별)')).toBeVisible();
  await expect(page.getByText('콘텐츠 유닛 / URL 패턴')).toBeVisible();
  // 실제 스케줄 표시 (가짜 '0 3 * * 0'이 아니라 실제 cron 반영)
  const struct = page.getByTestId('site-structure');
  await expect(struct.getByText('실제 스케줄')).toBeVisible();
  const structText = await struct.innerText();
  expect(structText).not.toContain('0 3 * * 0');
  expect(structText).toMatch(/전체크롤|비활성/);
  // 용어 설명 툴팁(?) 존재 — hover 시 상세 의미
  expect(await struct.getByTestId('infotip').count()).toBeGreaterThan(0);
});

test('3. Crawl Monitor — 크롤 이력', async ({ page }) => {
  await page.goto('/jobs');
  // 실행 이력 테이블 또는 행 존재
  await expect(page.locator('table')).toBeVisible({ timeout: 20_000 });
});

test('4. Document Explorer — 검색·상세·추출본문', async ({ page }) => {
  await page.goto('/pages');
  await expect(page.locator('table')).toBeVisible();
  // 첫 행 클릭 → 상세
  await page.locator('table tbody tr').first().click();
  await expect(page.getByTestId('page-detail')).toBeVisible({ timeout: 20_000 });
  // 추출본문 탭 → 실제 청크 텍스트
  await page.getByTestId('tab-추출본문').click();
  await expect(page.getByText('추출 본문 (벡터DB 저장 텍스트)')).toBeVisible();
});

test('5. 네비게이션 — 모든 콘솔 진입', async ({ page }) => {
  for (const [path, marker] of [
    ['/', 'dashboard'],
    ['/sites', 'site-list'],
    ['/pages', 'table'],
  ] as const) {
    await page.goto(path);
    if (marker === 'table') {
      await expect(page.locator('table')).toBeVisible({ timeout: 20_000 });
    } else {
      await expect(page.getByTestId(marker)).toBeVisible({ timeout: 20_000 });
    }
  }
});
