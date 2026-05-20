# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: id
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% id="c01-setup"
# ══════════════════════════════════════════════════════════════
#  MOPS 公開資訊觀測站 - 財務篩選分析工具
#  端點: mopsov.twse.com.tw (舊版，需 jcsession / Selenium)
# ══════════════════════════════════════════════════════════════

import requests
import pandas as pd
import numpy as np
import time
import random
from io import StringIO

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

pd.set_option('display.max_columns', None)
pd.set_option('display.float_format', lambda x: f'{x:.4f}')

TYPEK      = 'sii'
START_YEAR = 110
END_YEAR   = 114
YEARS      = list(range(START_YEAR, END_YEAR + 1))
MOPS_BASE  = 'https://mopsov.twse.com.tw/mops/web'
BASE_HDR   = {
    'User-Agent'  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Content-Type': 'application/x-www-form-urlencoded',
}

print(f'分析年度: {START_YEAR}~{END_YEAR}  |  類型: {TYPEK}')
print(f'Base URL: {MOPS_BASE}')


# %% id="c02-helpers"
def parse_num(s):
    # 含千分位逗號、括號（負數）的字串 → float
    if pd.isna(s):
        return np.nan
    s = str(s).replace(',', '').strip()
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        return float(s)
    except (ValueError, TypeError):
        return np.nan


def flatten_cols(df):
    # MultiIndex 欄位壓平為單層字串（MOPS 表格常有兩列標頭）
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            ' '.join(str(c) for c in col if str(c) not in ('nan', '')).strip()
            for col in df.columns
        ]
    return df


def find_col(df, *keywords):
    # 找出第一個名稱含任一 keyword 的欄位
    for col in df.columns:
        col_str = str(col)
        if any(kw in col_str for kw in keywords):
            return col
    return None


def parse_mops_html(html_text, year, season=None):
    # 解析 MOPS HTML，取最大表格並保留公司代號列
    try:
        tables = pd.read_html(StringIO(html_text), flavor='lxml')
    except Exception as e:
        print(f'    parse error: {e}')
        return None
    if not tables:
        return None
    df = max(tables, key=len).copy()
    df = flatten_cols(df)
    first_col = df.columns[0]
    mask = df[first_col].astype(str).str.match(r'^\d{3,6}$')
    df = df[mask].copy()
    if df.empty:
        return None
    df['year'] = year
    if season is not None:
        df['season'] = season
    return df.reset_index(drop=True)

print('輔助函式已載入')

# %% id="c03-session"
# ==============================================================
# Cell 3: 建立 Session
# 以 Selenium 訪問 mopsov 取得 jcsession，複製到 requests.Session 後關閉瀏覽器
# 使用防偵測設定，避免被伺服器辨識為自動化程式
# ==============================================================

# 強制覆寫 Base URL（舊版 mopsov 才有 jcsession；新版 mops.twse.com.tw 會封鎖）
MOPS_BASE = 'https://mopsov.twse.com.tw/mops/web'

def create_session(headless: bool = False) -> requests.Session:
    opts = Options()

    # ── 防偵測設定 ─────────────────────────────────────────
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/143.0.0.0 Safari/537.36'
    )
    opts.add_argument('--incognito')

    # ── 視窗模式 ───────────────────────────────────────────
    if headless:
        opts.add_argument('--headless=new')   # 新版 headless（較難被偵測）
        opts.add_argument('--window-size=1280,800')
    else:
        opts.add_argument('--start-maximized')

    # ── 其他穩定性設定 ─────────────────────────────────────
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')

    # 移除 WebDriver 特徵旗標
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )

    # 進一步隱藏 navigator.webdriver
    driver.execute_cdp_cmd(
        'Page.addScriptToEvaluateOnNewDocument',
        {'source': 'Object.defineProperty(navigator, webdriver, {get: () => undefined})'}
    )

    landing = MOPS_BASE + '/t163sb04'
    print(f'Visiting: {landing} ...', end=' ', flush=True)

    try:
        driver.get(landing)
        time.sleep(3)
        print(f'title: {driver.title[:40]}')

        sess = requests.Session()
        for c in driver.get_cookies():
            sess.cookies.set(c['name'], c['value'])

        cookie_names = list(sess.cookies.keys())
        print(f'Cookies: {cookie_names}')

        if 'jcsession' not in cookie_names:
            raise RuntimeError(
                'jcsession 未取得！請確認可連線至 mopsov.twse.com.tw'
            )

        print('Session ready.')
        return sess

    finally:
        driver.quit()   # 無論成功或失敗都關閉瀏覽器


# headless=False 開啟可見瀏覽器；改 True 可背景執行
SESSION = create_session(headless=False)

# %% id="c04-income-stmt"
# 綜合損益表彙總表 (採 IFRSs)
# 路徑: 彙總報表 → 財務報表 → 採IFRSs後綜合損益表彙總表
# 端點: mopsov ajax_t163sb04


# 隨機等待 3~7 秒，避免連續執行時被偵測為爬蟲
time.sleep(random.uniform(3, 7))

IS_AJAX = MOPS_BASE + '/ajax_t163sb04'
IS_PAGE = MOPS_BASE + '/t163sb04'


def fetch_income_stmt(sess, year, season='04', typek=TYPEK):
    payload = {
        'encodeURIComponent': '1', 'step': '1',
        'firstin': 'true', 'off': '1',
        'TYPEK': typek, 'year': str(year), 'season': season,
    }
    hdrs = {**BASE_HDR, 'Referer': IS_PAGE}
    try:
        r = sess.post(IS_AJAX, data=payload, headers=hdrs, timeout=40)
        r.encoding = 'utf-8'
        if not r.text.strip():
            print(f'    {year}: 空回應')
            return None
        if 'SECURITY REASONS' in r.text:
            print(f'    {year}: 被封鎖 – 請重新執行 Cell 3')
            return None
        return parse_mops_html(r.text, year, season)
    except Exception as e:
        print(f'    {year}: 錯誤 – {e}')
        return None


print('=== 損益表彙總表 (t163sb04) ===')
is_frames = []
for yr in YEARS:
    print(f'  {yr}...', end=' ', flush=True)
    df = fetch_income_stmt(SESSION, yr)
    if df is not None and not df.empty:
        is_frames.append(df)
        print(f'{len(df)} 家')
    else:
        print('無資料')
    time.sleep(1.5)

df_is_raw = pd.concat(is_frames, ignore_index=True) if is_frames else pd.DataFrame()
print(f'\n合計: {len(df_is_raw)} 筆')
if not df_is_raw.empty:
    print(f'涵蓋年度: {sorted(df_is_raw["year"].unique())}')
    print(f'欄位範例: {list(df_is_raw.columns[:5])}')

# %% id="c05-balance-sheet"
# 資產負債表彙總表 (採 IFRSs)
# 路徑: 彙總報表 → 財務報表 → 採IFRSs後資產負債表彙總表
# 端點: mopsov ajax_t163sb05


# 隨機等待 3~7 秒，避免連續執行時被偵測為爬蟲
time.sleep(random.uniform(3, 7))

BS_AJAX = MOPS_BASE + '/ajax_t163sb05'
BS_PAGE = MOPS_BASE + '/t163sb05'


def fetch_balance_sheet(sess, year, season='04', typek=TYPEK):
    payload = {
        'encodeURIComponent': '1', 'step': '1',
        'firstin': 'true', 'off': '1',
        'TYPEK': typek, 'year': str(year), 'season': season,
    }
    hdrs = {**BASE_HDR, 'Referer': BS_PAGE}
    try:
        r = sess.post(BS_AJAX, data=payload, headers=hdrs, timeout=40)
        r.encoding = 'utf-8'
        if not r.text.strip():
            print(f'    {year}: 空回應')
            return None
        if 'SECURITY REASONS' in r.text:
            print(f'    {year}: 被封鎖 – 請重新執行 Cell 3')
            return None
        return parse_mops_html(r.text, year, season)
    except Exception as e:
        print(f'    {year}: 錯誤 – {e}')
        return None


print('=== 資產負債表彙總表 (t163sb05) ===')
bs_frames = []
for yr in YEARS:
    print(f'  {yr}...', end=' ', flush=True)
    df = fetch_balance_sheet(SESSION, yr)
    if df is not None and not df.empty:
        bs_frames.append(df)
        print(f'{len(df)} 家')
    else:
        print('無資料')
    time.sleep(1.5)

df_bs_raw = pd.concat(bs_frames, ignore_index=True) if bs_frames else pd.DataFrame()
print(f'\n合計: {len(df_bs_raw)} 筆')
if not df_bs_raw.empty:
    print(f'涵蓋年度: {sorted(df_bs_raw["year"].unique())}')
    print(f'欄位範例: {list(df_bs_raw.columns[:5])}')

# %% id="c05b-cashflow"
# ══════════════════════════════════════════════════════════════
# 現金流量表彙總表 (採 IFRSs)
# 來源: https://mopsov.twse.com.tw/mops/web/t163sb20
# ══════════════════════════════════════════════════════════════


# 隨機等待 3~7 秒，避免連續執行時被偵測為爬蟲
time.sleep(random.uniform(3, 7))

CF_AJAX = MOPS_BASE + '/ajax_t163sb20'
CF_PAGE = MOPS_BASE + '/t163sb20'


def fetch_cash_flow(sess, year, season='4', typek=TYPEK):
    payload = {
        'encodeURIComponent': '1', 'step': '1',
        'firstin': 'true', 'off': '1', 'isQuery': 'Y',
        'TYPEK': typek, 'year': str(year), 'season': season,
    }
    hdrs = {**BASE_HDR, 'Referer': CF_PAGE}
    try:
        r = sess.post(CF_AJAX, data=payload, headers=hdrs, timeout=40)
        r.encoding = 'utf-8'
        if not r.text.strip():
            print(f'    {year} Q{season}: 空回應')
            return None
        if 'SECURITY REASONS' in r.text:
            print(f'    {year} Q{season}: 被封鎖 – 請重新執行 Cell 3')
            return None
        return parse_mops_html(r.text, year, season)
    except Exception as e:
        print(f'    {year} Q{season}: 錯誤 – {e}')
        return None


print('=== 現金流量表彙總表 (ajax_t163sb20) ===')
cf_frames = []
for yr in YEARS:
    print(f'  {yr}...', end=' ', flush=True)
    df = fetch_cash_flow(SESSION, yr, season='4')
    if df is not None and not df.empty:
        cf_frames.append(df)
        print(f'{len(df)} 家')
    else:
        print('無資料')
    time.sleep(1.5)

df_cf_raw = pd.concat(cf_frames, ignore_index=True) if cf_frames else pd.DataFrame()
print(f'\n合計: {len(df_cf_raw)} 筆')
if not df_cf_raw.empty:
    print(f'涵蓋年度: {sorted(df_cf_raw["year"].unique())}')
    print(f'欄位範例: {list(df_cf_raw.columns[:6])}')


# %% id="c06-dividends"
# ══════════════════════════════════════════════════════════════
# Cell 6: 股利分派情形 (t05st09_new) – 真實歷年配息紀錄
# ══════════════════════════════════════════════════════════════


# 隨機等待 3~7 秒，避免連續執行時被偵測為爬蟲
time.sleep(random.uniform(3, 7))

DIV_URL = MOPS_BASE + '/t05st09_new'


def make_div_driver():
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument('--disable-popup-blocking')
    opts.add_argument('--window-size=1280,900')
    opts.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
    )
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.add_experimental_option('prefs', {
        'profile.default_content_setting_values.popups': 1
    })
    d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',
        {'source': 'Object.defineProperty(navigator,"webdriver",{get:()=>undefined})'})
    d.set_page_load_timeout(30)
    d.set_script_timeout(15)
    return d


def get_popup_html(driver, year, typek, qrytype):
    driver.get(DIV_URL)

    # 等待頁面核心元素就緒
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.NAME, 'year'))
        )
    except Exception:
        print(f'    {year} qryType={qrytype}: 頁面載入逾時', flush=True)
        return None

    print(f'\n    URL={driver.current_url}', flush=True)

    # 設定年份
    for inp in driver.find_elements(By.TAG_NAME, 'input'):
        if inp.get_attribute('name') == 'year':
            driver.execute_script('arguments[0].value=arguments[1];', inp, str(year))

    # 設定市場類型
    for sel in driver.find_elements(By.TAG_NAME, 'select'):
        if sel.get_attribute('name') == 'TYPEK':
            try:
                Select(sel).select_by_value(typek)
            except Exception:
                pass

    # 點選 qryType radio
    for inp in driver.find_elements(By.TAG_NAME, 'input'):
        if inp.get_attribute('name') == 'qryType' and inp.get_attribute('value') == qrytype:
            driver.execute_script('arguments[0].click();', inp)
            break

    # 找查詢按鈕
    try:
        btns = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, '//input[@type="button" and contains(@value,"查詢")]')
            )
        )
    except Exception:
        print(f'    {year} qryType={qrytype}: 找不到查詢按鈕', flush=True)
        return None

    print(f'    查詢按鈕數量: {len(btns)}', flush=True)

    handles_before = set(driver.window_handles)
    main_handle    = driver.current_window_handle
    driver.execute_script('arguments[0].click();', btns[0])

    # 等待新視窗開啟
    try:
        WebDriverWait(driver, 20).until(
            EC.number_of_windows_to_be(len(handles_before) + 1)
        )
        popup_handle = (set(driver.window_handles) - handles_before).pop()
        driver.switch_to.window(popup_handle)

        # 等待 popup 內表格出現
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, 'table'))
        )
        html = driver.page_source
        driver.close()
        driver.switch_to.window(main_handle)
        return html

    except Exception as e:
        print(f'    彈窗等待失敗: {e}', flush=True)
        # fallback：如果新視窗已開啟但條件未觸發
        new_wins = set(driver.window_handles) - handles_before
        if new_wins:
            driver.switch_to.window(new_wins.pop())
            html = driver.page_source
            driver.close()
            driver.switch_to.window(main_handle)
            return html
        try:
            driver.switch_to.window(main_handle)
        except Exception:
            pass
        return None


def parse_div_html(html, year, qrytype):
    tables = pd.read_html(StringIO(html), flavor='lxml')
    frames = []
    for t in tables:
        if t.shape[1] < 15:
            continue
        t = flatten_cols(t.copy())
        first_col = t.columns[0]
        mask = t[first_col].astype(str).str.match(r'^\d{4}')
        t = t[mask].copy()
        if not t.empty:
            t['year']    = year
            t['qryType'] = qrytype
            frames.append(t)
    return pd.concat(frames, ignore_index=True) if frames else None


print('=== 股利分派情形 (t05st09_new) ===')
print(f'DIV_URL = {DIV_URL}')
print('建立 Selenium 驅動中...')
_div_driver = make_div_driver()

div_frames = []
for yr in YEARS:
    yr_frames = []
    for qt in ['1', '2']:
        print(f'\n  {yr} qryType={qt}...', end=' ', flush=True)
        html = get_popup_html(_div_driver, yr, TYPEK, qt)
        if html:
            df = parse_div_html(html, yr, qt)
            if df is not None:
                yr_frames.append(df)
                print(f'→ {len(df)} 列', end='  ')
            else:
                print('→ 解析失敗', end='  ')
        else:
            print('→ 無彈出視窗', end='  ')
        time.sleep(random.uniform(1, 2))
    if yr_frames:
        div_frames.append(pd.concat(yr_frames, ignore_index=True))

_div_driver.quit()
print('\n瀏覽器已關閉')

df_div_raw = pd.concat(div_frames, ignore_index=True) if div_frames else pd.DataFrame()
print(f'\n合計: {len(df_div_raw)} 筆')
if not df_div_raw.empty:
    print(f'涵蓋年度: {sorted(df_div_raw["year"].unique())}')
    print(f'欄位範例: {list(df_div_raw.columns[:6])}')


# %% id="c07-inspect"
# 執行此格確認欄位名稱，若 find_col 找不到正確欄位可據此手動補充關鍵字

for label, df in [
    ('損益表',     df_is_raw),
    ('資產負債表', df_bs_raw),
    ('現金流量表', df_cf_raw),
    ('股利分派',   df_div_raw),
]:
    sep = '=' * 60
    print(f'\n{sep}')
    print(f'  {label}  ({len(df)} 筆)')
    print(sep)
    if df.empty:
        print('  (無資料)')
        continue
    print('  欄位:')
    for col in df.columns:
        print(f'    {repr(col)}')
    print()
    display(df.head(2))


# %% id="c08-metrics"
def calc_is_metrics(df):
    id_col   = find_col(df, '代號')
    nm_col   = find_col(df, '公司名稱', '簡稱')
    rev_col  = find_col(df, '營業收入', '收入淨額')
    cogs_col = find_col(df, '營業成本', '成本')
    gp_col   = find_col(df, '毛利', '毛損')
    op_col   = find_col(df, '營業利益', '業利益')
    ni_col   = find_col(df, '本期淨利', '本期損益')
    eps_col  = find_col(df, '基本每股', 'EPS', '每股盈餘')

    print(f'  IS -> 代號:{id_col} | 收入:{rev_col} | 毛利:{gp_col}')
    print(f'        利益:{op_col} | 淨利:{ni_col} | EPS:{eps_col}')

    out = pd.DataFrame()
    out['id']           = df[id_col].astype(str).str.strip()  if id_col   else ''
    out['name']         = df[nm_col]                           if nm_col   else ''
    out['year']         = df['year']
    out['revenue']      = df[rev_col].apply(parse_num)         if rev_col  else np.nan
    out['gross_profit'] = df[gp_col].apply(parse_num)          if gp_col   else np.nan
    out['op_profit']    = df[op_col].apply(parse_num)          if op_col   else np.nan
    out['net_income']   = df[ni_col].apply(parse_num)          if ni_col   else np.nan
    out['eps']          = df[eps_col].apply(parse_num)         if eps_col  else np.nan

    if gp_col is None and cogs_col is not None:
        out['gross_profit'] = out['revenue'] - df[cogs_col].apply(parse_num)

    out['gross_margin'] = out['gross_profit'] / out['revenue']
    out['op_margin']    = out['op_profit']    / out['revenue']
    return out


def calc_bs_metrics(df):
    id_col     = find_col(df, '代號')
    nm_col     = find_col(df, '公司名稱', '簡稱')
    asset_col  = find_col(df, '資產總計', '資產總額', '資產合計')
    liab_col   = find_col(df, '負債總計', '負債總額', '負債合計')
    equity_col = find_col(df, '權益總計', '權益總額', '股東權益合計', '歸屬於母公司')

    print(f'  BS -> 代號:{id_col} | 資產:{asset_col}')
    print(f'        負債:{liab_col} | 權益:{equity_col}')

    out = pd.DataFrame()
    out['id']          = df[id_col].astype(str).str.strip()  if id_col     else ''
    out['name']        = df[nm_col]                          if nm_col     else ''
    out['year']        = df['year']
    out['assets']      = df[asset_col].apply(parse_num)      if asset_col  else np.nan
    out['liabilities'] = df[liab_col].apply(parse_num)       if liab_col   else np.nan
    out['equity']      = df[equity_col].apply(parse_num)     if equity_col else np.nan
    out['debt_ratio']  = out['liabilities'] / out['assets']
    return out


def calc_div_metrics(df):
    # t05st09_new 第一欄格式: "1101 - 台泥" 或 "1101台泥"
    first_col  = df.columns[0]
    cash_col   = find_col(df, '盈餘分配', '現金股利')  # 盈餘分配之現金股利(元/股)

    print(f'  DIV -> 第一欄:{first_col!r} | 現金股利欄:{cash_col!r}')

    out = pd.DataFrame()
    # 從第一欄提取公司代號（前4-6位數字）
    out['id']       = df[first_col].astype(str).str.extract(r'^(\d{4,6})')[0]
    out['year']     = df['year']
    out['cash_div'] = df[cash_col].apply(parse_num) if cash_col else np.nan
    out['has_dividend'] = out['cash_div'].fillna(0) > 0
    return out.dropna(subset=['id'])


print('計算損益表指標...')
df_is  = calc_is_metrics(df_is_raw)   if not df_is_raw.empty  else pd.DataFrame()

print('\n計算資產負債表指標...')
df_bs  = calc_bs_metrics(df_bs_raw)   if not df_bs_raw.empty  else pd.DataFrame()

print('\n計算股利指標...')
df_div = calc_div_metrics(df_div_raw) if not df_div_raw.empty else pd.DataFrame()

# ROE = 本期淨利 / 權益總計
if not df_is.empty and not df_bs.empty:
    roe_df = (
        df_is[['id', 'year', 'net_income']]
        .merge(df_bs[['id', 'year', 'equity']], on=['id', 'year'], how='inner')
    )
    roe_df['roe'] = roe_df['net_income'] / roe_df['equity']
    df_bs = df_bs.merge(roe_df[['id', 'year', 'roe']], on=['id', 'year'], how='left')
    print('\nROE 計算完成')

# 統計每年配息人數
if not df_div.empty:
    yr_stats = df_div[df_div['has_dividend']].groupby('year')['id'].nunique()
    print(f'\n每年現金配息家數:')
    print(yr_stats.to_string())

print('\n=== 損益表 (前 3 筆) ===')
display(df_is.head(3)) if not df_is.empty else print('無資料')
print('\n=== 資產負債表 (前 3 筆) ===')
display(df_bs.head(3)) if not df_bs.empty else print('無資料')
print('\n=== 股利 (前 5 筆) ===')
display(df_div.head(5)) if not df_div.empty else print('無資料')


def calc_cf_metrics(df):
    """現金流量表 (t163sb20) 欄位對應
    OCF: 營業活動之淨現金流入（流出）
    INV: 投資活動之淨現金流入（流出）
    FCF = OCF + INV（投資通常為負）
    """
    id_col  = find_col(df, '代號')
    nm_col  = find_col(df, '公司名稱', '簡稱')
    ocf_col = find_col(df, '營業活動', '營業現金')
    inv_col = find_col(df, '投資活動')

    print(f'  CF -> 代號:{id_col} | 營業現金流:{ocf_col} | 投資活動:{inv_col}')

    out = pd.DataFrame()
    out['id']   = df[id_col].astype(str).str.strip() if id_col else ''
    out['name'] = df[nm_col]                          if nm_col else ''
    out['year'] = df['year']
    out['ocf']  = df[ocf_col].apply(parse_num)        if ocf_col else np.nan
    out['inv']  = df[inv_col].apply(parse_num)         if inv_col else np.nan
    # FCF = OCF + 投資活動現金流（投資支出為負值，加總即為 OCF - CapEx 的近似）
    if ocf_col and inv_col:
        out['fcf'] = out['ocf'] + out['inv']
    elif ocf_col:
        out['fcf'] = out['ocf']  # fallback：無投資欄時以 OCF 代替
    else:
        out['fcf'] = np.nan
    return out


print('\n計算現金流量指標...')
df_cf = calc_cf_metrics(df_cf_raw) if not df_cf_raw.empty else pd.DataFrame()

print('\n=== 現金流量 (前 3 筆) ===')
display(df_cf.head(3)) if not df_cf.empty else print('無資料')


# %% id="c09-screening"
MIN_EPS_YEARS       = 5     # EPS > 0 至少連續幾年
MIN_DIV_YEARS       = 5     # 現金配息至少連續幾年
DEBT_THRESHOLD      = 0.50  # 負債比率上限
ROE_THRESHOLD       = 0.10  # ROE 下限 (10%)
MARGIN_TREND_CORR   = -0.10 # 毛利率/營業利益率趨勢相關係數下限（持平或走高）
OP_MARGIN_THRESHOLD = 0.10  # 營業利益率下限 (10%)，用於 Streamlit 顯示


# 1. EPS > 0 連續 MIN_EPS_YEARS 年
def check_eps(g):
    return (g['eps'] > 0).all() and len(g) >= MIN_EPS_YEARS

pass_eps = set(
    df_is.groupby('id').filter(check_eps)['id'].unique()
) if not df_is.empty else set()


# 2. 毛利率 & 營業利益率：持平或逐年走高（相關係數 >= -0.1）
def is_stable_or_rising(series):
    vals = series.dropna()
    if len(vals) < 2:
        return False
    corr = pd.Series(vals.values).corr(pd.Series(range(len(vals))))
    return pd.notna(corr) and corr >= MARGIN_TREND_CORR

def check_margin(g):
    g_s = g.sort_values('year')
    return (
        is_stable_or_rising(g_s['gross_margin']) and
        is_stable_or_rising(g_s['op_margin'])
    )

pass_margin = set(
    df_is.groupby('id').filter(check_margin)['id'].unique()
) if not df_is.empty else set()


# 3. 負債比率 < DEBT_THRESHOLD 每年
def check_debt(g):
    vals = g['debt_ratio'].dropna()
    return len(vals) > 0 and (vals < DEBT_THRESHOLD).all()

pass_debt = set(
    df_bs.groupby('id').filter(check_debt)['id'].unique()
) if not df_bs.empty else set()


# 4. ROE > ROE_THRESHOLD 每年
def check_roe(g):
    if 'roe' not in g.columns: return False
    vals = g['roe'].dropna()
    return len(vals) > 0 and (vals > ROE_THRESHOLD).all()

pass_roe = set(
    df_bs.groupby('id').filter(check_roe)['id'].unique()
) if (not df_bs.empty and 'roe' in df_bs.columns) else set()


# 5. 連續 MIN_DIV_YEARS 年有現金配息
if not df_div.empty:
    div_years = (
        df_div[df_div['has_dividend']]
        .groupby('id')['year'].nunique()
    )
    pass_div = set(div_years[div_years >= MIN_DIV_YEARS].index)
else:
    pass_div = set()


candidates = pass_eps & pass_margin & pass_debt & pass_roe & pass_div


sep = '-' * 58
print(sep)
print(f'篩選結果 ({TYPEK}  民國 {START_YEAR}~{END_YEAR}):')
print(f'  EPS > 0 連續 >= {MIN_EPS_YEARS} 年:            {len(pass_eps):>5} 家')
print(f'  毛利率 & 營業利益率 持平或走高:      {len(pass_margin):>5} 家')
print(f'  負債比率 < {DEBT_THRESHOLD*100:.0f}%:                  {len(pass_debt):>5} 家')
print(f'  ROE > {ROE_THRESHOLD*100:.0f}%:                      {len(pass_roe):>5} 家')
print(f'  連續 {MIN_DIV_YEARS} 年現金配息:              {len(pass_div):>5} 家')
print(sep)
print(f'  最終通過:                           {len(candidates):>5} 家')
print()
print(sorted(candidates))


# %% id="c10-report"
latest_yr = max(YEARS)

def get_latest(df):
    return df.sort_values('year').groupby('id').last().reset_index()

# 取分析範圍內全部公司（不限 candidates）
is_lt  = get_latest(df_is)  if not df_is.empty  else pd.DataFrame()
bs_lt  = get_latest(df_bs)  if not df_bs.empty  else pd.DataFrame()

avg_eps = (
    df_is.groupby('id')['eps'].mean().reset_index()
    .rename(columns={'eps': 'avg_eps'})
) if not df_is.empty else pd.DataFrame(columns=['id', 'avg_eps'])

if is_lt.empty:
    print('損益表無資料，請先執行 Cell 4')
else:
    report = is_lt[['id', 'name', 'eps', 'gross_margin', 'op_margin']].copy()

    if not bs_lt.empty:
        bs_cols = ['id', 'debt_ratio'] + (['roe'] if 'roe' in bs_lt.columns else [])
        report  = report.merge(bs_lt[bs_cols], on='id', how='left')

    if not avg_eps.empty:
        report = report.merge(avg_eps, on='id', how='left')

    # 篩選通過標記
    report['pass'] = report['id'].isin(candidates)
    report['篩選'] = report['pass'].map({True: '✅', False: '❌'})

    report['毛利率%']     = (report['gross_margin']           * 100).round(1)
    report['營業利益率%'] = (report['op_margin']               * 100).round(1)
    report['負債比%']     = (report.get('debt_ratio', np.nan) * 100).round(1)
    report['ROE%']        = (report.get('roe',         np.nan) * 100).round(1)

    out_cols = ['篩選', 'id', 'name', 'avg_eps', 'eps',
                '毛利率%', '營業利益率%', '負債比%', 'ROE%']
    out_cols = [c for c in out_cols if c in report.columns]

    rename_map = {
        'id'      : '代號',
        'name'    : '公司名稱',
        'avg_eps' : f'平均EPS({START_YEAR}~{END_YEAR})',
        'eps'     : f'EPS({latest_yr})',
    }
    final = (
        report[out_cols + ['pass']]
        .rename(columns=rename_map)
        .sort_values(['pass', 'ROE%'], ascending=[False, False])
        .drop(columns=['pass'])
        .reset_index(drop=True)
    )

    sep = '=' * 72
    n_all  = len(final)
    n_pass = report['pass'].sum()
    print(sep)
    print(f'  分析範圍全公司報表  (最新年度: 民國 {latest_yr} / 西元 {latest_yr + 1911})')
    print(f'  共 {n_all} 家公司，其中 {n_pass} 家通過篩選（✅），{n_all - n_pass} 家未通過（❌）')
    print(sep)

    display(final)

    out_path = 'stock_screening_result.csv'
    final.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f'\n已儲存至 {out_path}')


# ── 全年度多表合併 CSV（所有爬取年度合併，Streamlit 備用）──────────────────
def build_full_csv(df_is, df_bs, df_cf, df_div):
    """
    將各爬蟲表的所有年度資料以 (id, year) 為 key 橫向合併，
    輸出 mops_full_data.csv，包含所有公司 × 所有年度的指標。
    """
    frames = []

    if not df_is.empty and 'id' in df_is.columns:
        is_cols = [c for c in ['id','name','year','revenue','gross_profit','op_profit',
                               'net_income','eps','gross_margin','op_margin'] if c in df_is.columns]
        frames.append(df_is[is_cols].copy())

    base = frames[0] if frames else pd.DataFrame()

    if not df_bs.empty and 'id' in df_bs.columns:
        bs_cols = [c for c in ['id','year','assets','liabilities','equity',
                               'debt_ratio','roe'] if c in df_bs.columns]
        base = base.merge(df_bs[bs_cols], on=['id','year'], how='outer') if not base.empty                else df_bs[bs_cols].copy()

    if not df_cf.empty and 'id' in df_cf.columns:
        cf_cols = [c for c in ['id','year','ocf','inv','fcf'] if c in df_cf.columns]
        base = base.merge(df_cf[cf_cols], on=['id','year'], how='outer')

    # 配息：每年是否配息
    if not df_div.empty and 'has_dividend' in df_div.columns and 'id' in df_div.columns:
        div_yr = (df_div[df_div['has_dividend']]
                  .groupby(['id','year'])['has_dividend'].any()
                  .reset_index().rename(columns={'has_dividend': 'has_cash_div'}))
        base = base.merge(div_yr, on=['id','year'], how='outer')

    if not base.empty:
        # 百分比欄位
        for col, pct_col in [('gross_margin','gross_margin_pct'),
                              ('op_margin','op_margin_pct'),
                              ('debt_ratio','debt_ratio_pct'),
                              ('roe','roe_pct')]:
            if col in base.columns:
                base[pct_col] = (base[col] * 100).round(2)
        base = base.sort_values(['id','year']).reset_index(drop=True)
    return base

_full = build_full_csv(
    df_is, df_bs,
    df_cf  if not df_cf.empty  else pd.DataFrame(),
    df_div if not df_div.empty else pd.DataFrame(),
)
if not _full.empty:
    _full.to_csv('mops_full_data.csv', index=False, encoding='utf-8-sig')
    print(f'mops_full_data.csv 已儲存 ({len(_full)} 筆，{_full["id"].nunique()} 家公司，'
          f'{len(_full.columns)} 欄)')
else:
    print('mops_full_data.csv: 無資料')


# %% id="d81d0c6a"
# ══════════════════════════════════════════════════════════════
# Cell 11: 儲存資料 + 產生 Streamlit 應用程式 (stock_app.py)
# ══════════════════════════════════════════════════════════════
import pickle, subprocess, sys

subprocess.run([sys.executable, '-m', 'pip', 'install', 'streamlit', 'plotly', '-q'], check=False)

# ── 儲存 DataFrame ─────────────────────────────────────────
_save = {
    'df_is'      : df_is      if not df_is.empty      else pd.DataFrame(),
    'df_bs'      : df_bs      if not df_bs.empty      else pd.DataFrame(),
    'df_div'     : df_div     if not df_div.empty     else pd.DataFrame(),
    'df_cf'      : df_cf      if not df_cf.empty      else pd.DataFrame(),
    'candidates' : list(candidates) if candidates else [],
    'START_YEAR' : START_YEAR,
    'END_YEAR'   : END_YEAR,
    'YEARS'      : YEARS,
    'thresholds' : {
        'OP_MARGIN_THRESHOLD': OP_MARGIN_THRESHOLD,
        'DEBT_THRESHOLD'     : DEBT_THRESHOLD,
        'ROE_THRESHOLD'      : ROE_THRESHOLD,
    },
}
try:
    _save['final'] = final
except NameError:
    _save['final'] = pd.DataFrame()

with open('mops_data.pkl', 'wb') as _f:
    pickle.dump(_save, _f)

# ── 整合所有資料為單一 CSV（換環境時 Streamlit 可直接讀，不必重新爬）──────
def build_master_csv(df_is, df_bs, df_cf, df_div):
    if df_is.empty:
        return pd.DataFrame()

    def latest(df, extra_cols):
        if df.empty or 'id' not in df.columns:
            return pd.DataFrame()
        keep = [c for c in extra_cols if c in df.columns]
        return df.sort_values('year').groupby('id')[keep].last().reset_index()

    master = latest(df_is, ['name', 'eps', 'gross_margin', 'op_margin'])

    bs_extra = [c for c in ['debt_ratio', 'roe'] if c in df_bs.columns]
    if not df_bs.empty and bs_extra:
        master = master.merge(latest(df_bs, bs_extra), on='id', how='left')

    if not df_cf.empty:
        cf_extra = [c for c in ['ocf', 'fcf'] if c in df_cf.columns]
        if cf_extra:
            master = master.merge(latest(df_cf, cf_extra), on='id', how='left')

    if not df_div.empty and 'has_dividend' in df_div.columns:
        div_cnt = (df_div[df_div['has_dividend']]
                   .groupby('id')['year'].nunique()
                   .reset_index().rename(columns={'year': 'div_years'}))
        master = master.merge(div_cnt, on='id', how='left')

    master['gross_margin_pct'] = (master['gross_margin'] * 100).round(2)
    master['op_margin_pct']    = (master['op_margin']    * 100).round(2)
    if 'debt_ratio' in master.columns:
        master['debt_ratio_pct'] = (master['debt_ratio'] * 100).round(2)
    if 'roe' in master.columns:
        master['roe_pct'] = (master['roe'] * 100).round(2)
    return master


_master = build_master_csv(
    df_is, df_bs,
    df_cf  if not df_cf.empty  else pd.DataFrame(),
    df_div if not df_div.empty else pd.DataFrame(),
)
if not _master.empty:
    _master.to_csv('mops_master.csv', index=False, encoding='utf-8-sig')
    print(f'mops_master.csv 已儲存 ({len(_master)} 家公司，{len(_master.columns)} 欄)')
else:
    print('mops_master.csv: 無資料可儲存')

print('mops_data.pkl 已儲存')

# ── 寫出 stock_app.py ──────────────────────────────────────
_app_code = '''
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import pickle

st.set_page_config(page_title="MOPS 股市分析儀表板", page_icon="📊", layout="wide")

@st.cache_data
def load():
    try:
        with open("mops_data.pkl", "rb") as f:
            return pickle.load(f)
    except FileNotFoundError:
        # pkl 不存在時，從 mops_master.csv 建立最簡化的資料結構
        import os
        if not os.path.exists("mops_master.csv"):
            return {}
        df = pd.read_csv("mops_master.csv", dtype={"id": str})
        df_is_csv = df.rename(columns={"gross_margin_pct": "gross_margin",
                                        "op_margin_pct":    "op_margin"})
        df_is_csv["year"] = 0
        return {
            "df_is": df_is_csv, "df_bs": df_is_csv,
            "df_div": pd.DataFrame(), "df_cf": pd.DataFrame(),
            "candidates": [], "final": pd.DataFrame(),
            "START_YEAR": 109, "END_YEAR": 113, "YEARS": list(range(109, 114)),
            "thresholds": {}, "_from_csv": True,
        }
raw        = load()
START_YEAR = raw.get("START_YEAR", 109)
END_YEAR   = raw.get("END_YEAR",   113)
candidates = set(str(x) for x in raw.get("candidates", []))
thresholds = raw.get("thresholds", {})

def normalize(df):
    if df.empty:
        return df
    df = df.copy()
    if "id" not in df.columns:
        for c in df.columns:
            if "代號" in str(c):
                df = df.rename(columns={c: "id"})
                break
    if "id" in df.columns:
        df["id"] = df["id"].astype(str).str.extract(r"(\\d{4,6})")[0].fillna("")
        df = df[df["id"] != ""]
    return df

df_is  = normalize(raw.get("df_is",  pd.DataFrame()))
df_bs  = normalize(raw.get("df_bs",  pd.DataFrame()))
df_div = normalize(raw.get("df_div", pd.DataFrame()))
df_cf  = normalize(raw.get("df_cf",  pd.DataFrame()))
final  = raw.get("final", pd.DataFrame())

name_map = {}
if not df_is.empty and "id" in df_is.columns and "name" in df_is.columns:
    name_map = df_is.groupby("id")["name"].first().to_dict()

def to_label(code):
    name = name_map.get(str(code), "")
    return f"{code} {name}".strip() if name else str(code)

def add_label(df):
    if df.empty or "id" not in df.columns:
        return df
    df = df.copy()
    df["label"] = df["id"].apply(to_label)
    return df

df_is  = add_label(df_is)
df_bs  = add_label(df_bs)
df_div = add_label(df_div)
df_cf  = add_label(df_cf)

# ── Sidebar ─────────────────────────────────────────────────
st.sidebar.title("📊 MOPS 股市篩選")
st.sidebar.caption(f"分析年度：民國 {START_YEAR}~{END_YEAR}")

# AI 供應鏈主題分類
AI_GROUPS = {
    "晶圓代工與先進封裝"         : ["2330", "3711", "2449"],
    "ASIC 與 IP 設計服務"        : ["2454", "3661", "3443", "3035", "6533"],
    "AI 伺服器代工與系統整合"    : ["2317", "2382", "3231", "6669", "2356", "2301", "2324"],
    "散熱模組與液冷技術"         : ["3017", "3653", "2421", "3013"],
    "電源供應器與綠能電力"       : ["2308", "2303", "6285"],
    "高階導軌與機殼"             : ["2059", "8210", "3693", "3015"],
    "高速傳訊與 IC 晶片"         : ["5269", "4968", "6756"],
    "高階 PCB、銅箔基板與 ABF 載板": ["2383", "3037", "2368", "6213", "3189", "8046"],
}
ALL_AI_IDS = [i for ids in AI_GROUPS.values() for i in ids]

# 全部公司（來自爬取資料）
if not df_is.empty and "id" in df_is.columns:
    all_ids = sorted(df_is["id"].dropna().unique().tolist())
elif not df_bs.empty and "id" in df_bs.columns:
    all_ids = sorted(df_bs["id"].dropna().unique().tolist())
else:
    all_ids = []

if not all_ids:
    st.error("找不到公司清單，請先執行 Notebook Cell 1~11")
    st.stop()

all_labels  = [to_label(i) for i in all_ids]
cand_labels = [to_label(i) for i in all_ids if i in candidates]

show_mode = st.sidebar.radio(
    "顯示範圍",
    ["僅篩選通過", "AI供應鏈分類", "全部公司", "自訂選擇"],
    index=0,
)

if show_mode == "僅篩選通過":
    sel_labels = cand_labels if cand_labels else all_labels[:min(10, len(all_labels))]

elif show_mode == "AI供應鏈分類":
    sel_groups = st.sidebar.multiselect(
        "選擇 AI 供應鏈類別",
        list(AI_GROUPS.keys()),
        default=list(AI_GROUPS.keys()),
    )
    ai_ids_raw = [i for g in sel_groups for i in AI_GROUPS[g]]
    seen_set = set()
    ai_ids_unique = [x for x in ai_ids_raw if x not in seen_set and not seen_set.add(x)]
    sel_labels = [to_label(i) for i in ai_ids_unique if i in set(all_ids)]
    if not sel_labels:
        sel_labels = cand_labels[:min(10, len(cand_labels))]

elif show_mode == "全部公司":
    sel_labels = all_labels

else:  # 自訂選擇
    sel_labels = st.sidebar.multiselect(
        "選擇公司 (代號 + 名稱)",
        all_labels,
        default=cand_labels[:min(8, len(cand_labels))] or all_labels[:8],
    )

selected = [lbl.split(" ")[0] for lbl in sel_labels]

year_range = st.sidebar.slider("年度範圍", START_YEAR, END_YEAR, (START_YEAR, END_YEAR))
st.sidebar.markdown("---")

# 篩選條件說明
if thresholds:
    st.sidebar.subheader("篩選條件")
    st.sidebar.markdown(f"""
- EPS > 0 連續年
- 營業利益率 > {thresholds.get('OP_MARGIN_THRESHOLD', 0.10)*100:.0f}%
- 負債比 < {thresholds.get('DEBT_THRESHOLD', 0.50)*100:.0f}%
- ROE > {thresholds.get('ROE_THRESHOLD', 0.10)*100:.0f}%
- 毛利率/營業利益率趨勢相關係數下限 > -0.10
    """)
st.sidebar.info("重新爬取後執行 Cell 11 更新資料，再重啟 App")

if not selected:
    st.warning("請在左側選擇至少一家公司")
    st.stop()

def flt(df):
    if df.empty or "id" not in df.columns or "year" not in df.columns:
        return df
    return df[df["id"].isin(selected) & df["year"].between(year_range[0], year_range[1])].copy()

is_f  = flt(df_is)
bs_f  = flt(df_bs)
div_f = flt(df_div)
cf_f  = flt(df_cf)

# ── 頁面標題 + KPI ─────────────────────────────────────────
st.title("📊 MOPS 上市公司財務分析儀表板")
if not is_f.empty and "eps" in is_f.columns:
    lat  = is_f[is_f["year"] == is_f["year"].max()]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("顯示公司數", len(selected))
    k2.metric("平均 EPS", f"{lat['eps'].mean():.2f} 元")
    k3.metric("平均毛利率",
              f"{lat['gross_margin'].mean()*100:.1f}%" if "gross_margin" in lat else "—")
    if not bs_f.empty and "roe" in bs_f.columns:
        k4.metric("平均 ROE",
                  f"{bs_f[bs_f['year']==bs_f['year'].max()]['roe'].mean()*100:.1f}%")
    else:
        k4.metric("全部公司數", len(all_ids))
st.markdown("---")

t1, t2, t3, t4, t5 = st.tabs(
    ["🏆 篩選總覽", "📈 損益趨勢", "🏦 資產負債", "💰 股利分析", "💵 現金流量"])

# ── Tab1：篩選總覽 ───────────────────────────────────────────
with t1:
    # 直接從目前選取範圍建表，顯示所有 selected 公司，不限篩選通過
    if not is_f.empty:
        lat_is = is_f[is_f["year"] == is_f["year"].max()].copy()
        avg_e  = (is_f.groupby("id")["eps"].mean()
                  .reset_index().rename(columns={"eps": "avg_eps"}))
        tab1_df = lat_is[[c for c in ["id", "label", "name", "eps",
                                       "gross_margin", "op_margin"]
                           if c in lat_is.columns]].copy()
        tab1_df = tab1_df.merge(avg_e, on="id", how="left")
        if not bs_f.empty:
            lat_bs  = bs_f[bs_f["year"] == bs_f["year"].max()]
            bs_need = ["id"] + [c for c in ["debt_ratio", "roe"] if c in lat_bs.columns]
            tab1_df = tab1_df.merge(lat_bs[bs_need], on="id", how="left")
        for col, pct in [("gross_margin", "毛利率%"), ("op_margin", "營業利益率%"),
                          ("debt_ratio",   "負債比%"),  ("roe",       "ROE%")]:
            if col in tab1_df.columns:
                tab1_df[pct] = (tab1_df[col] * 100).round(1)
        show_cols = (
            [c for c in ["label", "name"] if c in tab1_df.columns] +
            [c for c in ["avg_eps", "eps", "毛利率%", "營業利益率%", "負債比%", "ROE%"]
             if c in tab1_df.columns]
        )
        st.dataframe(
            tab1_df[show_cols]
              .rename(columns={"name": "公司名稱",
                               "avg_eps": "平均EPS", "label": "代號+名稱"})
              .reset_index(drop=True),
            use_container_width=True, height=400
        )
    if not is_f.empty and not bs_f.empty:
        li = is_f[is_f["year"] == is_f["year"].max()].copy()
        lb = bs_f[bs_f["year"] == bs_f["year"].max()].copy()
        need = ["id", "debt_ratio"] + (["roe"] if "roe" in lb.columns else [])
        need = [c for c in need if c in lb.columns]
        cols_i = [c for c in ["id", "label", "name", "eps", "gross_margin", "op_margin"] if c in li.columns]
        mg = li[cols_i].merge(lb[need], on="id", how="left") if "id" in li.columns else pd.DataFrame()
        if not mg.empty:
            if "gross_margin" in mg: mg["gm%"] = (mg["gross_margin"]*100).round(1)
            if "op_margin"    in mg: mg["op%"] = (mg["op_margin"]   *100).round(1)
            if "debt_ratio"   in mg: mg["dr%"] = (mg["debt_ratio"]  *100).round(1)
            if "roe"          in mg: mg["roe%"]= (mg["roe"]         *100).round(1)
            if "is_cand" not in mg.columns:
                mg["篩選通過"] = mg["id"].isin(candidates).map({True:"✅通過",False:"❌未通過"})
            mg["AI分類"] = mg["id"].apply(
                lambda x: next((g for g, ids in AI_GROUPS.items() if x in ids), "其他"))
            txt_col = "label" if "label" in mg.columns else "id"
            c1, c2 = st.columns(2)
            with c1:
                if "roe%" in mg and "dr%" in mg:
                    fig = px.scatter(mg, x="dr%", y="roe%", text=txt_col,
                        color="篩選通過" if "篩選通過" in mg else "roe%",
                        color_discrete_map={"✅通過":"#00CC96","❌未通過":"#EF553B"},
                        title="ROE vs 負債比率",
                        labels={"dr%":"負債比(%)","roe%":"ROE(%)"})
                    fig.update_traces(textposition="top center", marker_size=10)
                    fig.add_vline(x=50, line_dash="dash", line_color="red")
                    fig.add_hline(y=10, line_dash="dash", line_color="green")
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                if "gm%" in mg and "op%" in mg:
                    fig2 = px.scatter(mg, x="gm%", y="op%", text=txt_col,
                        color="篩選通過" if "篩選通過" in mg else None,
                        color_discrete_map={"✅通過":"#00CC96","❌未通過":"#EF553B"},
                        title="毛利率 vs 營業利益率",
                        labels={"gm%":"毛利率(%)","op%":"營業利益率(%)"})
                    fig2.add_hline(y=10, line_dash="dash", line_color="orange",
                                   annotation_text="10%基準")
                    fig2.update_traces(textposition="top center", marker_size=10)
                    st.plotly_chart(fig2, use_container_width=True)

# ── Tab2：損益趨勢 ───────────────────────────────────────────
with t2:
    if is_f.empty:
        st.info("無損益表資料")
    else:
        ip  = is_f.sort_values("year")
        lbl = "label" if "label" in ip.columns else "id"
        c1, c2 = st.columns(2)
        with c1:
            if "eps" in ip.columns:
                fe = px.line(ip, x="year", y="eps", color=lbl, markers=True,
                    title="EPS 歷年趨勢",
                    labels={"year":"民國年","eps":"EPS(元)",lbl:"公司"})
                fe.add_hline(y=0, line_dash="dash", line_color="red")
                st.plotly_chart(fe, use_container_width=True)
        with c2:
            if "gross_margin" in ip.columns:
                fg = px.line(ip, x="year", y="gross_margin", color=lbl, markers=True,
                    title="毛利率歷年趨勢",
                    labels={"year":"民國年","gross_margin":"毛利率",lbl:"公司"})
                fg.update_yaxes(tickformat=".1%")
                st.plotly_chart(fg, use_container_width=True)
        if "op_margin" in ip.columns:
            fo = px.line(ip, x="year", y="op_margin", color=lbl, markers=True,
                title="營業利益率歷年趨勢",
                labels={"year":"民國年","op_margin":"營業利益率",lbl:"公司"})
            fo.update_yaxes(tickformat=".1%")
            fo.add_hline(y=0.10, line_dash="dash", line_color="orange",
                         annotation_text="10%基準")
            st.plotly_chart(fo, use_container_width=True)
        if "eps" in ip.columns:
            st.subheader("各年 EPS 比較")
            fb = px.bar(ip, x=lbl, y="eps", color="year", barmode="group",
                title="各公司 EPS 分年比較",
                labels={lbl:"公司","eps":"EPS(元)","year":"民國年"})
            st.plotly_chart(fb, use_container_width=True)

# ── Tab3：資產負債 ───────────────────────────────────────────
with t3:
    if bs_f.empty:
        st.info("無資產負債表資料")
    else:
        bp  = bs_f.sort_values("year")
        lbl = "label" if "label" in bp.columns else "id"
        c1, c2 = st.columns(2)
        with c1:
            if "debt_ratio" in bp.columns:
                fd = px.line(bp, x="year", y="debt_ratio", color=lbl, markers=True,
                    title="負債比率歷年趨勢",
                    labels={"year":"民國年","debt_ratio":"負債比率",lbl:"公司"})
                fd.update_yaxes(tickformat=".1%")
                fd.add_hline(y=0.5, line_dash="dash", line_color="red",
                             annotation_text="50%上限")
                st.plotly_chart(fd, use_container_width=True)
        with c2:
            if "roe" in bp.columns:
                fr = px.line(bp, x="year", y="roe", color=lbl, markers=True,
                    title="ROE 歷年趨勢",
                    labels={"year":"民國年","roe":"ROE",lbl:"公司"})
                fr.update_yaxes(tickformat=".1%")
                fr.add_hline(y=0.10, line_dash="dash", line_color="green",
                             annotation_text="10%基準")
                st.plotly_chart(fr, use_container_width=True)
        st.subheader("資產結構 (最新年度)")
        lb2 = bp[bp["year"] == bp["year"].max()].copy()
        if "assets" in lb2.columns and "liabilities" in lb2.columns:
            lb2["equity_v"] = lb2["assets"] - lb2["liabilities"]
            x_col = "label" if "label" in lb2.columns else "id"
            stk = lb2[[x_col, "liabilities", "equity_v"]].melt(
                id_vars=x_col, var_name="項目", value_name="金額")
            stk["項目"] = stk["項目"].map({"liabilities":"負債","equity_v":"股東權益"})
            fs = px.bar(stk, x=x_col, y="金額", color="項目", barmode="stack",
                title="資產 = 負債 + 股東權益",
                color_discrete_map={"負債":"#EF553B","股東權益":"#00CC96"},
                labels={x_col:"公司"})
            st.plotly_chart(fs, use_container_width=True)

# ── Tab4：股利分析 ───────────────────────────────────────────
with t4:
    if div_f.empty:
        st.info("無股利資料（Cell 6 尚未成功抓取）")
    else:
        lbl = "label" if "label" in div_f.columns else "id"
        cash_col = next((c for c in div_f.columns if "現金股利" in str(c) and "元" in str(c)),
                        "cash_div" if "cash_div" in div_f.columns else None)
        if cash_col:
            dp = div_f[div_f[cash_col].notna()].copy()
            dp["cdv"] = pd.to_numeric(dp[cash_col], errors="coerce")
            da = dp.groupby(["id","year","label"] if "label" in dp.columns else ["id","year"])["cdv"].max().reset_index()
            if not da.empty:
                lbl_da = "label" if "label" in da.columns else "id"
                fdb = px.bar(da, x="year", y="cdv", color=lbl_da, barmode="group",
                    title="各公司現金股利 (元/股)",
                    labels={"year":"民國年","cdv":"現金股利(元/股)",lbl_da:"公司"})
                st.plotly_chart(fdb, use_container_width=True)
                fdl = px.line(da, x="year", y="cdv", color=lbl_da, markers=True,
                    title="現金股利趨勢",
                    labels={"year":"民國年","cdv":"現金股利(元/股)",lbl_da:"公司"})
                st.plotly_chart(fdl, use_container_width=True)
        if "has_dividend" in div_f.columns:
            st.subheader("配息年份熱力圖")
            piv_src = div_f.copy()
            piv_src["y_key"] = piv_src["label"] if "label" in piv_src.columns else piv_src["id"]
            piv = piv_src.groupby(["y_key","year"])["has_dividend"].any().unstack(fill_value=False).astype(int)
            fh = px.imshow(piv, title="配息紀錄 (綠=有 紅=無)",
                color_continuous_scale=["#EF553B","#00CC96"], aspect="auto",
                labels={"x":"民國年","y":"公司","color":"配息"})
            fh.update_coloraxes(showscale=False)
            st.plotly_chart(fh, use_container_width=True)

# ── Tab5：現金流量 ───────────────────────────────────────────
with t5:
    if cf_f.empty:
        st.info("無現金流量資料（Cell 現金流量表 尚未成功抓取）")
    else:
        cp  = cf_f.sort_values("year")
        lbl = "label" if "label" in cp.columns else "id"
        c1, c2 = st.columns(2)
        with c1:
            if "ocf" in cp.columns:
                foc = px.line(cp, x="year", y="ocf", color=lbl, markers=True,
                    title="營業現金流歷年趨勢 (萬元)",
                    labels={"year":"民國年","ocf":"營業現金流(萬)",lbl:"公司"})
                foc.add_hline(y=0, line_dash="dash", line_color="red")
                st.plotly_chart(foc, use_container_width=True)
        with c2:
            if "fcf" in cp.columns:
                ffc = px.line(cp, x="year", y="fcf", color=lbl, markers=True,
                    title="自由現金流歷年趨勢 (萬元)",
                    labels={"year":"民國年","fcf":"自由現金流(萬)",lbl:"公司"})
                ffc.add_hline(y=0, line_dash="dash", line_color="red")
                st.plotly_chart(ffc, use_container_width=True)
        if "ocf" in cp.columns:
            lat_cf = cp[cp["year"] == cp["year"].max()]
            lbl_cf = "label" if "label" in lat_cf.columns else "id"
            fcf_cols = [lbl_cf, "ocf"] + (["fcf"] if "fcf" in lat_cf.columns else [])
            st.subheader(f"最新年度現金流量比較 (民國 {cp['year'].max()})")
            st.dataframe(
                lat_cf[fcf_cols].rename(columns={"ocf":"營業現金流(萬)","fcf":"自由現金流(萬)",lbl_cf:"公司"})
                .sort_values("營業現金流(萬)", ascending=False)
                .reset_index(drop=True),
                use_container_width=True
            )

'''

with open('stock_app.py', 'w', encoding='utf-8') as _f:
    _f.write(_app_code.lstrip('\n'))
print('stock_app.py 已寫出（全部公司 + 現金流量）')
print('請重新執行 Cell 12 重啟 Streamlit')


# %% id="a009647c"
# ══════════════════════════════════════════════════════════════
# Cell 12: 啟動 Streamlit 儀表板
# ══════════════════════════════════════════════════════════════
import subprocess, sys, time, webbrowser

# 背景啟動 Streamlit
_proc = subprocess.Popen(
    [sys.executable, '-m', 'streamlit', 'run', 'stock_app.py',
     '--server.port', '8501',
     '--server.headless', 'true',
     '--browser.gatherUsageStats', 'false'],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

time.sleep(3)  # 等待服務啟動

URL = 'http://localhost:8501'
print('=' * 50)
print(f'  Streamlit 已啟動：{URL}')
print('=' * 50)
print()
print('  操作說明:')
print('    左側 Sidebar  → 選擇公司、年度範圍')
print('    Tab 1 篩選總覽 → 結果表 + ROE/負債散點圖')
print('    Tab 2 損益趨勢 → EPS、毛利率、營業利益率折線圖')
print('    Tab 3 資產負債 → 負債比、ROE、資產結構')
print('    Tab 4 股利分析 → 配息金額、配息熱力圖')
print()
print('  停止服務請執行: _proc.terminate()')

# 自動在瀏覽器開啟
try:
    webbrowser.open(URL)
except Exception:
    pass
