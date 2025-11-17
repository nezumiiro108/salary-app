import streamlit as st
import datetime
import math
import calendar
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# --- 1. ページ設定 ---
st.set_page_config(page_title="給料帳", layout="centered")

# --- 2. デザイン (ダークモード & コンパクト & シンプル) ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    .block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 600px; }
    .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; margin-top: 5px; }
    .cal-header { text-align: center; font-size: 10px; font-weight: bold; color: #aaa; padding-bottom: 2px; }
    .cal-day { background-color: #262730; border: 1px solid #333; border-radius: 4px; height: 50px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
    .cal-num { font-size: 10px; color: #ccc; margin: 0; line-height: 1.2; }
    .cal-pay { font-size: 8.5px; font-weight: bold; color: #4da6ff; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; padding: 0 2px; }
    .cal-today { border: 1px solid #4da6ff; background-color: #1e2a3a; }
    .cal-empty { background-color: transparent; border: none; }
    .total-area { text-align: center; padding: 10px; background-color: #262730; border-radius: 8px; border: 1px solid #444; color: #fff; margin-bottom: 15px; }
    .total-amount { font-size: 22px; font-weight: bold; color: #4da6ff; }
    .total-sub { font-size: 10px; color: #aaa; }
    .history-row { border-bottom: 1px solid #333; padding: 8px 0; display: flex; justify-content: space-between; align-items: center; color: #eee; }
    .tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 5px; font-weight: normal; }
    .tag-work { background: #1c3a5e; color: #aaddff; }
    .tag-break { background: #4a1a1a; color: #ffaaaa; }
    .tag-drive { background: #1a4a3a; color: #aaffdd; }
    .stSlider { padding-bottom: 10px !important; }
    .stSlider label { font-size: 12px; color: #ddd !important; }
    </style>
""", unsafe_allow_html=True)

# --- 3. Google Sheets 接続 ---
conn = st.connection("gsheets", type=GSheetsConnection)

# データ取得・保存関数
def get_all_records_df():
    """recordsシートから全データをDataFrameとして取得"""
    try:
        df = conn.read(worksheet="records", ttl=0)
        # カラムの型変換（エラー防止）
        df = df.fillna(0)
        df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
        df['date_str'] = df['date_str'].astype(str)
        return df
    except Exception:
        # シートが空などの場合、空のDFを返す
        return pd.DataFrame(columns=['id', 'date_str', 'type', 'start_h', 'start_m', 'end_h', 'end_m', 'distance_km', 'pay_amount', 'duration_minutes'])

def save_record_to_sheet(new_record_dict):
    """新しいレコードを追記"""
    df = get_all_records_df()
    
    # 新しいIDの発番
    new_id = 1
    if not df.empty and 'id' in df.columns:
        if df['id'].max() > 0:
            new_id = df['id'].max() + 1
    
    new_record_dict['id'] = new_id
    
    # 新しい行を作成して結合
    new_row = pd.DataFrame([new_record_dict])
    updated_df = pd.concat([df, new_row], ignore_index=True)
    
    # 保存
    conn.update(worksheet="records", data=updated_df)
    st.cache_data.clear() # キャッシュクリア

def delete_record_from_sheet(record_id):
    """指定IDのレコードを削除"""
    df = get_all_records_df()
    if not df.empty:
        updated_df = df[df['id'] != record_id]
        conn.update(worksheet="records", data=updated_df)
        st.cache_data.clear()

def get_records_by_date(date_str):
    """特定の日付のデータを辞書リストで返す"""
    df = get_all_records_df()
    if df.empty: return []
    
    # 日付でフィルタリング
    filtered = df[df['date_str'] == date_str].copy()
    # 辞書リストに変換
    return filtered.to_dict('records')

def get_min_record_date():
    """一番古い日付を取得"""
    df = get_all_records_df()
    if df.empty: return datetime.date.today()
    
    try:
        min_date_str = df['date_str'].min()
        return datetime.datetime.strptime(min_date_str, '%Y-%m-%d').date()
    except:
        return datetime.date.today()

# 設定の読み書き (settingsシートを使用)
def load_setting(key, default_value):
    try:
        df = conn.read(worksheet="settings", ttl=0)
        if df.empty: return default_value
        
        # key列から検索
        row = df[df['key'] == key]
        if not row.empty:
            return row.iloc[0]['value']
        return default_value
    except:
        return default_value

def save_setting(key, value):
    try:
        df = conn.read(worksheet="settings", ttl=0)
    except:
        df = pd.DataFrame(columns=['key', 'value'])
        
    # 既存のキーがあれば更新、なければ追加
    if key in df['key'].values:
        df.loc[df['key'] == key, 'value'] = str(value)
    else:
        new_row = pd.DataFrame([{'key': key, 'value': str(value)}])
        df = pd.concat([df, new_row], ignore_index=True)
        
    conn.update(worksheet="settings", data=df)
    st.cache_data.clear()

# --- 4. 計算ロジック ---
NIGHT_START = 22 * 60
NIGHT_END = 28 * 60
OVERTIME_THRESHOLD = 8 * 60

def calculate_driving_allowance(km):
    if km < 0.1: return 0
    if km < 10: return 150
    if km >= 340: return 3300
    return 300 + (math.floor((km - 10) / 30) * 300)

def calculate_daily_total(records, base_wage):
    work_minutes = set()
    break_minutes = set()
    drive_pay_total = 0
    
    for r in records:
        # DataFrameから来るデータはfloatの可能性があるためint変換
        sh, sm = int(r['start_h']), int(r['start_m'])
        eh, em = int(r['end_h']), int(r['end_m'])
        
        if r['type'] == 'DRIVE':
            drive_pay_total += calculate_driving_allowance(float(r['distance_km']))
            for m in range(sh*60 + sm, eh*60 + em): work_minutes.add(m)
        elif r['type'] == 'WORK':
            for m in range(sh*60 + sm, eh*60 + em): work_minutes.add(m)
        elif r['type'] == 'BREAK':
            for m in range(sh*60 + sm, eh*60 + em): break_minutes.add(m)
    
    actual_work = sorted(list(work_minutes - break_minutes))
    total_min = len(actual_work)
    
    base_min_rate = base_wage / 60
    total_work_pay = 0.0
    
    for i, m in enumerate(actual_work):
        rate = base_min_rate
        if NIGHT_START <= m < NIGHT_END:
            rate += (base_min_rate * 0.25)
        if i >= OVERTIME_THRESHOLD:
            rate += (base_min_rate * 0.25)
        total_work_pay += rate
        
    return math.floor(total_work_pay) + drive_pay_total, total_min

def format_time_label(h, m):
    prefix = "翌" if h >= 24 else ""
    disp_h = h - 24 if h >= 24 else h
    return f"{prefix}{disp_h:02}:{m:02}"

# --- 5. セッション ---
if 'base_wage' not in st.session_state:
    # 読み込み失敗時は初期値1190
    try:
        loaded = load_setting('base_wage', '1190')
        st.session_state.base_wage = int(float(loaded))
    except:
        st.session_state.base_wage = 1190

today = datetime.date.today()
if 'view_year' not in st.session_state: st.session_state.view_year = today.year
if 'view_month' not in st.session_state: st.session_state.view_month = today.month

def change_month(amount):
    m = st.session_state.view_month + amount
    y = st.session_state.view_year
    if m > 12: m = 1; y += 1
    elif m < 1: m = 12; y -= 1
    st.session_state.view_month = m
    st.session_state.view_year = y

def get_calendar_summary(wage):
    df = get_all_records_df()
    if df.empty: return {}
    
    # 日付ごとにグループ化
    summary = {}
    # date_strでユニークな日付を取得
    unique_dates = df['date_str'].unique()
    
    for d in unique_dates:
        day_df = df[df['date_str'] == d]
        records = day_df.to_dict('records')
        pay, mins = calculate_daily_total(records, wage)
        summary[d] = {'pay': pay, 'min': mins}
        
    return summary

# --- 6. メイン表示 ---
tab_input, tab_calendar, tab_setting = st.tabs(["日次入力", "カレンダー", "設定"])

# ==========================================
# TAB: 設定
# ==========================================
with tab_setting:
    st.write("")
    st.subheader("設定")
    new_wage = st.number_input("基本時給 (円)", value=st.session_state.base_wage, step=10)
    if st.button("保存"):
        st.session_state.base_wage = new_wage
        save_setting('base_wage', new_wage)
        st.success("保存しました")
        st.rerun()
    
    st.markdown("""
    <div style='font-size:12px; color:#aaa; margin-top:10px;'>
    ・日中: 基本給<br>
    ・夜勤 (22:00-28:00): 1.25倍<br>
    ・残業 (8時間超): 1.25倍<br>
    ・運転手当: 距離に応じて加算
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# TAB: 日次入力
# ==========================================
with tab_input:
    st.write("")
    
    # 入力日付
    input_date = st.date_input("日付", value=datetime.date.today())
    input_date_str = input_date.strftime("%Y-%m-%d")
    
    st.markdown("---")
    record_type = st.radio("タイプ", ["勤務", "休憩", "運転"], horizontal=True, label_visibility="collapsed")
    
    def time_sliders(label, kh, km, dh, dm):
        curr_h = st.session_state.get(kh, dh)
        curr_m = st.session_state.get(km, dm)
        st.markdown(f"<div style='font-size:11px; font-weight:bold; color:#aaa;'>{label}: <span style='color:#4da6ff;'>{format_time_label(curr_h, curr_m)}</span></div>", unsafe_allow_html=True)
        c1, c2 = st.columns([1.3, 1])
        with c1: vh = st.slider("時", 0, 33, dh, key=kh, label_visibility="collapsed")
        with c2: vm = st.slider("分", 0, 59, dm, key=km, step=1, label_visibility="collapsed")
        return vh, vm

    sh, sm = time_sliders("開始", "sh_in", "sm_in", 9, 0)
    eh, em = time_sliders("終了", "eh_in", "em_in", 18, 0)
    
    dist_km = 0
    if "運転" in record_type:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        curr_km = st.session_state.get('d_km', 0.0)
        curr_allowance = calculate_driving_allowance(curr_km)
        st.markdown(f"""
            <div style='display:flex; justify-content:space-between; align-items:end; margin-bottom:2px;'>
                <div style='font-size:11px; font-weight:bold; color:#55bb88;'>距離: {curr_km} km</div>
                <div style='font-size:11px; font-weight:bold; color:#55bb88;'>手当: ¥{curr_allowance:,}</div>
            </div>
        """, unsafe_allow_html=True)
        dist_km = st.slider("km", 0.0, 350.0, 0.0, 0.1, key="d_km", label_visibility="collapsed")
    
    st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
    
    if st.button("追加", type="primary", use_container_width=True):
        if (sh*60+sm) >= (eh*60+em):
            st.error("開始 < 終了 にしてください")
        elif "運転" in record_type and dist_km == 0:
            st.error("距離を入力してください")
        else:
            r_code = "DRIVE" if "運転" in record_type else "BREAK" if "休憩" in record_type else "WORK"
            
            # データ作成 (辞書型)
            new_data = {
                "date_str": input_date_str,
                "type": r_code,
                "start_h": sh, "start_m": sm,
                "end_h": eh, "end_m": em,
                "distance_km": dist_km,
                "pay_amount": 0, # 計算は表示時に行うので0で保存
                "duration_minutes": (eh*60+em) - (sh*60+sm)
            }
            
            save_record_to_sheet(new_data)
            st.rerun()
            
    # 履歴
    st.markdown("<div style='font-size:12px; font-weight:bold; color:#888; margin-top:20px; margin-bottom:5px;'>登録済みリスト</div>", unsafe_allow_html=True)
    
    day_recs = get_records_by_date(input_date_str)
    day_pay, day_min = calculate_daily_total(day_recs, st.session_state.base_wage)
    
    if not day_recs:
        st.caption("なし")
    else:
        for r in day_recs:
            c1, c2 = st.columns([5, 1])
            with c1:
                # int変換
                s_h, s_m = int(r['start_h']), int(r['start_m'])
                e_h, e_m = int(r['end_h']), int(r['end_m'])
                
                time_str = f"{format_time_label(s_h, s_m)} ~ {format_time_label(e_h, e_m)}"
                if r['type'] == "DRIVE":
                    html = f"<div class='history-row'><div><span class='tag tag-drive'>運転</span> <span style='font-size:12px;'>{time_str} ({r['distance_km']}km)</span></div></div>"
                elif r['type'] == "BREAK":
                    html = f"<div class='history-row'><div><span class='tag tag-break'>休憩</span> <span style='font-size:12px;'>{time_str}</span></div></div>"
                else:
                    html = f"<div class='history-row'><div><span class='tag tag-work'>勤務</span> <span style='font-size:12px;'>{time_str}</span></div></div>"
                st.markdown(html, unsafe_allow_html=True)
            with c2:
                st.write("") 
                if st.button("✕", key=f"del_{r['id']}"):
                    delete_record_from_sheet(r['id'])
                    st.rerun()
        
        st.markdown(f"""
            <div class="total-area" style="margin-top:10px; background-color:#1f2933;">
                <div class="total-sub">実働 {day_min//60}時間{day_min%60}分</div>
                <div class="total-amount">計 ¥{day_pay:,}</div>
            </div>
        """, unsafe_allow_html=True)

# ==========================================
# TAB: カレンダー
# ==========================================
with tab_calendar:
    
    min_record_date = get_min_record_date()
    min_date_limit = min_record_date.replace(day=1)
    current_date_obj = datetime.date.today()
    max_date_limit = current_date_obj.replace(day=1)
    view_date = datetime.date(st.session_state.view_year, st.session_state.view_month, 1)
    
    can_go_prev = view_date > min_date_limit
    can_go_next = view_date < max_date_limit

    c1, c2, c3 = st.columns([1, 3, 1])
    with c1: 
        if st.button("◀", use_container_width=True, disabled=not can_go_prev): 
            change_month(-1); st.rerun()
    with c2:
        st.markdown(f"<div style='text-align:center; font-weight:bold; padding-top:5px; color:#bbb;'>{st.session_state.view_year}年 {st.session_state.view_month}月</div>", unsafe_allow_html=True)
    with c3:
        if st.button("▶", use_container_width=True, disabled=not can_go_next): 
            change_month(1); st.rerun()
    
    st.write("")
    summary = get_calendar_summary(st.session_state.base_wage)
    
    total_pay = 0
    total_min = 0
    s_date = datetime.date(st.session_state.view_year, st.session_state.view_month, 1)
    e_date = datetime.date(st.session_state.view_year, st.session_state.view_month, calendar.monthrange(st.session_state.view_year, st.session_state.view_month)[1])
    curr = s_date
    while curr <= e_date:
        d_str = curr.strftime("%Y-%m-%d")
        if d_str in summary:
            total_pay += summary[d_str]['pay']
            total_min += summary[d_str]['min']
        curr += datetime.timedelta(days=1)

    st.markdown(f"""
    <div class="total-area">
        <div class="total-sub">今月の支給予定額</div>
        <div class="total-amount">¥ {total_pay:,}</div>
        <div class="total-sub" style="margin-top:5px;">総稼働: {total_min//60}時間{total_min%60}分</div>
    </div>
    """, unsafe_allow_html=True)

    html_parts = []
    html_parts.append('<div class="calendar-grid">')
    
    for w in ["日", "月", "火", "水", "木", "金", "土"]:
        color = "#ff6666" if w=="日" else "#4da6ff" if w=="土" else "#aaa"
        html_parts.append(f'<div class="cal-header" style="color:{color}">{w}</div>')
    
    cal_obj = calendar.Calendar(firstweekday=6)
    month_days = cal_obj.monthdayscalendar(st.session_state.view_year, st.session_state.view_month)
    today_d = datetime.date.today()

    for week in month_days:
        for day in week:
            if day == 0:
                html_parts.append('<div class="cal-day cal-empty"></div>')
            else:
                curr_d = datetime.date(st.session_state.view_year, st.session_state.view_month, day)
                d_str = curr_d.strftime("%Y-%m-%d")
                
                pay_val = 0
                if d_str in summary:
                    pay_val = summary[d_str]['pay']
                
                extra_cls = "cal-today" if curr_d == today_d else ""
                pay_disp = f"¥{pay_val:,}" if pay_val > 0 else ""
                pay_div = f'<div class="cal-pay">{pay_disp}</div>' if pay_disp else ""
                
                html_parts.append(f'<div class="cal-day {extra_cls}"><div class="cal-num">{day}</div>{pay_div}</div>')
                
    html_parts.append('</div>') 
    st.markdown("".join(html_parts), unsafe_allow_html=True)