import streamlit as st
import datetime
import math
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from decimal import Decimal, ROUND_FLOOR, getcontext
import calendar
import re

# --- 1. 設定と定数 ---
getcontext().prec = 30
PAGE_TITLE = "給料帳"
NIGHT_START = 22 * 60
NIGHT_END = 27 * 60
OVERTIME_THRESHOLD = 8 * 60

st.set_page_config(page_title=PAGE_TITLE, layout="centered")

# --- 2. CSSデザイン ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    .block-container { padding-top: 2rem; padding-bottom: 5rem; max_width: 600px; }
    
    /* UIパーツの強制配色 */
    div[data-testid*="stButton"] > button { background-color: #262730 !important; color: white !important; border-color: #555 !important; }
    div[data-testid*="stButton"] > button[kind="primary"] { background-color: #4da6ff !important; color: #0e1117 !important; border-color: #4da6ff !important; }
    .stTextInput input, .stDateInput input, .stNumberInput input { color: white !important; background-color: #1f2933 !important; border-color: #333 !important; }
    .stTextInput label, .stDateInput label, .stNumberInput label { color: #ddd !important; }
    
    /* カレンダーグリッド */
    .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; margin-top: 5px; }
    .cal-header { text-align: center; font-size: 10px; font-weight: bold; color: #aaa; padding-bottom: 2px; }
    .cal-day { background-color: #262730; border: 1px solid #333; border-radius: 4px; height: 50px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
    .cal-num { font-size: 10px; color: #ccc; margin: 0; line-height: 1.2; }
    .cal-pay { font-size: 8.5px; font-weight: bold; color: #4da6ff; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; padding: 0 2px; }
    .cal-today { border: 1px solid #4da6ff; background-color: #1e2a3a; }
    .cal-empty { background-color: transparent; border: none; }
    
    /* 合計・履歴 */
    .total-area { text-align: center; padding: 10px; background-color: #262730; border-radius: 8px; border: 1px solid #444; color: #fff; margin-bottom: 15px; }
    .total-amount { font-size: 22px; font-weight: bold; color: #4da6ff; }
    .total-sub { font-size: 10px; color: #aaa; }
    .history-row { padding: 6px 0; display: flex; justify-content: space-between; align-items: center; color: #eee; border-bottom: 1px solid #333; }
    
    /* タグ */
    .tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 5px; font-weight: normal; display: inline-block; }
    .tag-work { background: #1c3a5e; color: #aaddff; }
    .tag-break { background: #4a1a1a; color: #ffaaaa; }
    .tag-drive { background: #1a4a3a; color: #aaffdd; }
    .tag-direct { background: #5e4a1c; color: #ffddaa; border: 1px solid #cc9900; }
    .tag-other { background: #444444; color: #dddddd; border: 1px solid #666; }
    .tag-plus { color: #aaddff; font-weight: bold; }
    .tag-minus { color: #ffaaaa; font-weight: bold; }
    
    div[data-testid="column"] button { float: right; }
    </style>
""", unsafe_allow_html=True)

# --- 3. データベース操作 ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_all_records_df():
    try:
        df = conn.read(worksheet="records", ttl=600)
        df = df.fillna(0)
        df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
        if 'user_id' not in df.columns: df['user_id'] = 'default' 
        return df
    except Exception:
        return pd.DataFrame(columns=['id', 'user_id', 'date_str', 'type', 'start_h', 'start_m', 'end_h', 'end_m', 'distance_km', 'pay_amount', 'duration_minutes'])

def crud_record(action, record_data=None, record_id=None):
    with st.spinner("処理中..."):
        df = get_all_records_df()
        if action == "save" and record_data:
            new_id = df['id'].max() + 1 if not df.empty and 'id' in df.columns and df['id'].max() > 0 else 1
            record_data['id'] = new_id
            updated_df = pd.concat([df, pd.DataFrame([record_data])], ignore_index=True)
        elif action == "delete" and record_id is not None:
            updated_df = df[df['id'] != record_id] if not df.empty else df
        else:
            return
        conn.update(worksheet="records", data=updated_df)
        st.cache_data.clear()

def get_records_by_date(date_str, user_id):
    df = get_all_records_df()
    if df.empty: return []
    filtered = df[(df['date_str'] == date_str) & (df['user_id'] == user_id)].copy()
    return filtered.to_dict('records')

def get_all_records_by_user(user_id):
    df = get_all_records_df()
    if df.empty: return []
    filtered = df[df['user_id'] == user_id].copy()
    return filtered.to_dict('records')

def get_min_record_date_by_user(user_id):
    df = get_all_records_df()
    df_user = df[df['user_id'] == user_id]
    if df_user.empty: return datetime.date.today()
    try:
        min_date_str = df_user['date_str'].min()
        return datetime.datetime.strptime(min_date_str, '%Y-%m-%d').date()
    except:
        return datetime.date.today()

# --- 設定関連 ---
def load_setting(key, default_value, user_id="common"):
    try:
        df = conn.read(worksheet="settings", ttl=3600)
        if df.empty or 'user_id' not in df.columns: return default_value
        df['value'] = df['value'].astype(str)
        row = df[(df['user_id'] == user_id) & (df['key'] == key)]
        if not row.empty: return row.iloc[0]['value']
        if key == 'base_wage' and user_id != 'common': save_setting(key, default_value, user_id)
        return default_value
    except:
        return default_value

def save_setting(key, value, user_id="common"):
    with st.spinner("設定保存中..."):
        try:
            df = conn.read(worksheet="settings", ttl=0)
        except:
            df = pd.DataFrame(columns=['user_id', 'key', 'value'])
        match_index = df[(df['user_id'] == user_id) & (df['key'] == key)].index
        if not match_index.empty:
            df.loc[match_index[0], 'value'] = str(value)
        else:
            new_row = pd.DataFrame([{'user_id': user_id, 'key': key, 'value': str(value)}])
            df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="settings", data=df)
        st.cache_data.clear()

def update_user_id_across_sheets(old_id, new_id, new_password, auth_users):
    with st.spinner("ID移行中..."):
        # Records update
        df_rec = get_all_records_df()
        if not df_rec.empty:
            df_rec.loc[df_rec['user_id'] == old_id, 'user_id'] = new_id
            conn.update(worksheet="records", data=df_rec)
        
        # Settings update
        df_set = conn.read(worksheet="settings", ttl=0)
        if not df_set.empty:
            df_set.loc[df_set['user_id'] == old_id, 'user_id'] = new_id
            # Auth update
            for key in auth_users:
                if key == old_id:
                    auth_rows = df_set[df_set['value'] == old_id]
                    for idx, row in auth_rows.iterrows():
                        if row['key'].endswith('_id'):
                            user_num = row['key'].split('_')[1]
                            df_set.loc[idx, 'value'] = new_id
                            df_set.loc[df_set['key'] == f'user_{user_num}_pw', 'value'] = new_password
            conn.update(worksheet="settings", data=df_set)
        st.cache_data.clear()
        return True

def load_auth_users():
    try:
        df = conn.read(worksheet="settings", ttl=600)
        auth_users = {"admin": "admin"}
        user_rows = df[df['key'].str.endswith('_id')]
        for _, row in user_rows.iterrows():
            user_num = row['key'].split('_')[1]
            user_id = row['value']
            pw_rows = df[df['key'] == f'user_{user_num}_pw']
            if not pw_rows.empty:
                user_pw = pw_rows.iloc[0]['value']
                if user_id != "admin": auth_users[user_id] = user_pw
        return auth_users
    except: return {"admin": "admin"}

def get_next_user_number(df):
    user_rows = df[df['key'].str.endswith('_id')]
    nums = [int(key.split('_')[1]) for key in user_rows['key'] if key.startswith('user_') and len(key.split('_')) == 3]
    return max(nums) + 1 if nums else 1

# --- 4. 計算ロジック (精度保証版) ---
def calculate_driving_allowance(km):
    km = int(km)
    if km == 0: return 0
    if km < 10: return 150
    if km >= 340: return 3300
    return 300 + (math.floor((km - 10) / 30) * 300)

def calculate_direct_drive_pay(km):
    return int(km) * 25

def calculate_daily_total(records, base_wage, drive_wage):
    base_wage_dec = Decimal(base_wage)
    drive_wage_dec = Decimal(drive_wage)
    timeline = [None] * (48 * 60)
    fixed_pay = Decimal(0)
    
    sorted_records = sorted(records, key=lambda x: int(x['start_h']) * 60 + int(x['start_m']))
    
    for r in sorted_records:
        try:
            sh, sm = int(float(r['start_h'])), int(float(r['start_m']))
            eh, em = int(float(r['end_h'])), int(float(r['end_m']))
            dist = Decimal(r['distance_km'])
        except: continue
        
        if r['type'] == 'OTHER': fixed_pay += Decimal(r['pay_amount'])
        elif r['type'] == 'DRIVE_DIRECT': fixed_pay += Decimal(calculate_direct_drive_pay(dist))
        elif r['type'] == 'DRIVE':
            fixed_pay += Decimal(calculate_driving_allowance(dist))
            for m in range(sh*60+sm, eh*60+em): timeline[m] = 'DRIVE' if m < len(timeline) else None
        elif r['type'] == 'WORK':
            for m in range(sh*60+sm, eh*60+em): timeline[m] = 'WORK' if m < len(timeline) else None
        elif r['type'] == 'BREAK':
            for m in range(sh*60+sm, eh*60+em): timeline[m] = 'BREAK' if m < len(timeline) else None

    total_wage_points = Decimal(0)
    work_mins = 0
    
    for i, act in enumerate(timeline):
        if act not in ['WORK', 'DRIVE']: continue
        
        rate = drive_wage_dec if act == 'DRIVE' else base_wage_dec
        mult = Decimal(1)
        
        is_night = (NIGHT_START <= i < NIGHT_END)
        is_over = (work_mins >= OVERTIME_THRESHOLD)
        
        if is_night and is_over: mult = Decimal('1.5625')
        elif is_night or is_over: mult = Decimal('1.25')
            
        total_wage_points += rate * mult
        work_mins += 1
    
    final_pay = (total_wage_points / Decimal(60)).to_integral_value(rounding=ROUND_FLOOR)
    return int(final_pay + fixed_pay), work_mins

def format_time(h, m):
    prefix = "翌" if h >= 24 else ""
    return f"{prefix}{h-24 if h>=24 else h:02}:{m:02}"

# --- 5. セッション管理 ---
def init_session():
    if 'authenticated' not in st.session_state: st.session_state.authenticated = False
    if 'user_id' not in st.session_state: st.session_state.user_id = None
    
    today = datetime.date.today()
    if 'view_year' not in st.session_state: st.session_state.view_year = today.year
    if 'view_month' not in st.session_state: st.session_state.view_month = today.month

# ★ ユーザー切り替え時の設定クリア関数
def clear_user_settings():
    for key in ['base_wage', 'wage_drive', 'closing_day']:
        if key in st.session_state:
            del st.session_state[key]

init_session()

# ログイン成功後のロード
if st.session_state.authenticated:
    uid = st.session_state.user_id
    if 'base_wage' not in st.session_state:
        try:
            st.session_state.base_wage = int(float(load_setting('base_wage', '1190', uid)))
            st.session_state.wage_drive = int(float(load_setting('wage_drive', '1050', uid)))
            st.session_state.closing_day = int(float(load_setting('closing_day', '31', uid)))
        except:
            st.session_state.base_wage = 1190
            st.session_state.wage_drive = 1050
            st.session_state.closing_day = 31

def change_month(amount):
    m = st.session_state.view_month + amount
    y = st.session_state.view_year
    if m > 12: m = 1; y += 1
    elif m < 1: m = 12; y -= 1
    st.session_state.view_month = m
    st.session_state.view_year = y

# --- 6. UI Components ---
def time_inputs_row(label, kh, km, dh, dm, disabled=False):
    col_t = "#aaa" if not disabled else "#555"
    col_v = "#4da6ff" if not disabled else "#555"
    curr_h = st.session_state.get(kh, None)
    curr_m = st.session_state.get(km, None)
    disp = format_time(curr_h, curr_m) if (curr_h is not None and curr_m is not None) else "--:--"
    
    st.markdown(f"<div style='font-size:11px; font-weight:bold; color:{col_t};'>{label}: <span style='color:{col_v};'>{disp}</span></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1.3, 1])
    with c1: vh = st.number_input("時", 0, 33, value=None, key=kh, placeholder="時", label_visibility="collapsed", disabled=disabled)
    with c2: vm = st.number_input("分", 0, 59, value=None, key=km, placeholder="分", label_visibility="collapsed", disabled=disabled)
    return vh, vm

def render_history_list(records):
    st.markdown("<div style='font-size:12px; font-weight:bold; color:#888; margin-top:20px; margin-bottom:5px;'>登録済みリスト</div>", unsafe_allow_html=True)
    if not records:
        st.caption("なし")
        return

    for r in records:
        c1, c2 = st.columns([0.85, 0.15])
        with c1:
            rtype = r['type']
            if rtype == 'OTHER':
                amt = int(r['pay_amount'])
                tag, cls = "その他", "tag-other"
                txt = f"<span class='{'tag-plus' if amt>=0 else 'tag-minus'}'>{'+' if amt>=0 else '-'}{abs(amt):,}</span>"
            else:
                sh, sm = int(float(r['start_h'])), int(float(r['start_m']))
                eh, em = int(float(r['end_h'])), int(float(r['end_m']))
                t_str = f"{format_time(sh, sm)} ~ {format_time(eh, em)}"
                
                if rtype == 'DRIVE_DIRECT':
                    dist, pay = int(float(r['distance_km'])), int(float(r['distance_km'])) * 25
                    tag, cls, txt = "直行直帰", "tag-direct", f"<span style='color:#ffddaa; font-size:10px;'>{dist}km / ¥{pay:,}</span>"
                elif rtype == 'DRIVE':
                    dist, pay = int(float(r['distance_km'])), calculate_driving_allowance(Decimal(r['distance_km']))
                    tag, cls, txt = "運転", "tag-drive", f"{t_str} <span style='color:#aaffdd; font-size:10px;'>({dist}km/¥{pay:,})</span>"
                elif rtype == 'BREAK':
                    tag, cls, txt = "休憩", "tag-break", t_str
                else:
                    tag, cls, txt = "勤務", "tag-work", t_str
            
            st.markdown(f"<div class='history-row'><div><span class='tag {cls}'>{tag}</span> <span style='font-size:12px;'>{txt}</span></div></div>", unsafe_allow_html=True)
        
        with c2:
            st.markdown('<div style="height: 4px;"></div>', unsafe_allow_html=True)
            if st.button("✕", key=f"del_{r['id']}"):
                crud_record("delete", record_id=r['id'])
                st.rerun()

def render_calendar_view(summary, year, month, closing_day):
    if closing_day == 31:
        s_date, e_date = datetime.date(year, month, 1), datetime.date(year, month, calendar.monthrange(year, month)[1])
        label = f"{year}年{month}月1日～{e_date.day}日 (カレンダー月)"
    else:
        prev_m = 12 if month == 1 else month - 1
        prev_y = year - 1 if month == 1 else year
        s_date = datetime.date(prev_y, prev_m, min(closing_day + 1, calendar.monthrange(prev_y, prev_m)[1]))
        e_date = datetime.date(year, month, min(closing_day, calendar.monthrange(year, month)[1]))
        label = f"{prev_y}年{prev_m}月{s_date.day}日～{year}年{month}月{e_date.day}日 ({closing_day}日締め)"

    t_pay, t_min = 0, 0
    curr = s_date
    while curr <= e_date:
        d_str = curr.strftime("%Y-%m-%d")
        if d_str in summary:
            t_pay += summary[d_str]['pay']
            t_min += summary[d_str]['min']
        curr += datetime.timedelta(days=1)

    st.markdown(f"""<div class="total-area"><div class="total-sub">計算期間: {label}</div><div class="total-amount">¥ {t_pay:,}</div><div class="total-sub" style="margin-top:5px;">総稼働: {t_min//60}時間{t_min%60}分</div></div>""", unsafe_allow_html=True)

    cal_obj = calendar.Calendar(firstweekday=6)
    html_parts = ['<div class="calendar-grid">']
    for w in ["日", "月", "火", "水", "木", "金", "土"]:
        html_parts.append(f'<div class="cal-header" style="color:{"#ff6666" if w=="日" else "#4da6ff" if w=="土" else "#aaa"}">{w}</div>')
    
    today_d = datetime.date.today()
    for week in cal_obj.monthdayscalendar(year, month):
        for day in week:
            if day == 0:
                html_parts.append('<div class="cal-day cal-empty"></div>')
            else:
                d_str = datetime.date(year, month, day).strftime("%Y-%m-%d")
                pay_val = summary.get(d_str, {'pay': 0})['pay']
                cls = "cal-today" if datetime.date(year, month, day) == today_d else ""
                pay_div = f'<div class="cal-pay">¥{pay_val:,}</div>' if pay_val > 0 else ""
                html_parts.append(f'<div class="cal-day {cls}"><div class="cal-num">{day}</div>{pay_div}</div>')
    
    html_parts.append('</div>')
    st.markdown("".join(html_parts), unsafe_allow_html=True)

# --- メインフロー ---
def login_form():
    st.title("ログイン")
    users = load_auth_users()
    with st.form("login"):
        uid = st.text_input("ユーザーID")
        pw = st.text_input("パスワード", type="password")
        if st.form_submit_button("ログイン"):
            if uid in users and users[uid] == pw:
                st.session_state.authenticated = True
                st.session_state.user_id = uid
                # ★ ログイン成功時に以前のユーザー設定が残らないようクリア
                clear_user_settings()
                st.success(f"ログイン成功: {uid}さん")
                st.rerun()
            else: st.error("IDまたはパスワードが違います")

if not st.session_state.authenticated:
    login_form()
else:
    is_admin = st.session_state.user_id == "admin"
    tabs = st.tabs(["記録", "カレンダー", "設定"] + (["管理者"] if is_admin else []))
    
    # --- TAB 1: 記録 ---
    with tabs[0]:
        st.write("")
        # 日付選択 (上部へ)
        input_date = st.date_input("日付", value=datetime.date.today())
        input_date_str = input_date.strftime("%Y-%m-%d")
        
        st.markdown("---")
        rec_type = st.radio("タイプ", ["勤務", "休憩", "運転", "その他"], horizontal=True, label_visibility="collapsed")
        
        if rec_type == "その他":
            st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
            c1, c2 = st.columns([1, 1.5])
            kind = c1.radio("区分", ["支給 (+)", "控除 (-)"], label_visibility="collapsed")
            amt = c2.number_input("金額 (円)", min_value=0, step=100)
            st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
            if st.button("追加", type="primary", width='stretch'):
                if amt <= 0: st.error("金額を入力してください")
                else:
                    crud_record("save", {"user_id": st.session_state.user_id, "date_str": input_date_str, "type": "OTHER", "start_h":0, "start_m":0, "end_h":0, "end_m":0, "distance_km":0, "pay_amount": amt if "支給" in kind else -amt, "duration_minutes":0})
                    st.rerun()
        else:
            is_drv = rec_type == "運転"
            is_direct = st.toggle("直行直帰 (時給なし・25円/km)", False) if is_drv else False
            disabled = is_direct
            
            sh, sm = time_inputs_row("開始", "sh", "sm", None, None, disabled)
            eh, em = time_inputs_row("終了", "eh", "em", None, None, disabled)
            
            dist = 0
            if is_drv:
                curr_km = int(st.session_state.get('d_km', 0))
                allow = calculate_direct_drive_pay(curr_km) if is_direct else calculate_driving_allowance(curr_km)
                label = "支給" if is_direct else "手当"
                col = "#ffddaa" if is_direct else "#55bb88"
                st.markdown(f"<div style='display:flex; justify-content:space-between; font-size:11px; font-weight:bold; color:{col};'><div>距離: {curr_km} km</div><div>{label}: ¥{allow:,}</div></div>", unsafe_allow_html=True)
                dist = st.number_input("km", 0, 350, 0, 1, key="d_km", label_visibility="collapsed")

            st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
            if st.button("追加", type="primary", width='stretch'):
                if not disabled and (sh is None or sm is None or eh is None or em is None): st.error("時間を入力してください")
                elif not disabled and (sh*60+sm) >= (eh*60+em): st.error("開始 < 終了 にしてください")
                else:
                    code = "DRIVE_DIRECT" if is_direct else "DRIVE" if is_drv else "BREAK" if rec_type == "休憩" else "WORK"
                    s_h, s_m = (0, 0) if is_direct else (sh, sm)
                    e_h, e_m = (0, 0) if is_direct else (eh, em)
                    duration = 0 if is_direct else (e_h*60+e_m)-(s_h*60+s_m)
                    
                    crud_record("save", {"user_id": st.session_state.user_id, "date_str": input_date_str, "type": code, "start_h": s_h, "start_m": s_m, "end_h": e_h, "end_m": e_m, "distance_km": dist, "pay_amount": 0, "duration_minutes": duration})
                    st.rerun()

        # リスト表示
        day_recs = get_records_by_date(input_date_str, st.session_state.user_id)
        d_pay, d_min = calculate_daily_total(day_recs, st.session_state.base_wage, st.session_state.wage_drive)
        
        render_history_list(day_recs)
        
        st.markdown(f"""<div class="total-area" style="margin-top:10px; background-color:#1f2933;"><div class="total-sub">実働 {d_min//60}時間{d_min%60}分</div><div class="total-amount">計 ¥{d_pay:,}</div></div>""", unsafe_allow_html=True)

    # --- TAB 2: カレンダー ---
    with tabs[1]:
        v_y = st.session_state.view_year
        v_m = st.session_state.view_month
        
        # ナビゲーション
        c1, c2, c3 = st.columns([1, 3, 1])
        min_rec = get_min_record_date_by_user(st.session_state.user_id).replace(day=1)
        cur_d = datetime.date.today().replace(day=1)
        view_d = datetime.date(v_y, v_m, 1)
        
        if c1.button("◀", width='stretch', disabled=view_d <= min_rec): change_month(-1); st.rerun()
        c2.markdown(f"<div style='text-align:center; font-weight:bold; padding-top:5px; color:#bbb;'>{v_y}年 {v_m}月</div>", unsafe_allow_html=True)
        if c3.button("▶", width='stretch', disabled=view_d >= cur_d): change_month(1); st.rerun()
        
        st.write("")
        # 集計と描画
        all_r = get_all_records_by_user(st.session_state.user_id)
        summary = {}
        from itertools import groupby
        all_r.sort(key=lambda x: x['date_str'])
        for date, group in groupby(all_r, key=lambda x: x['date_str']):
            p, m = calculate_daily_total(list(group), st.session_state.base_wage, st.session_state.wage_drive)
            summary[date] = {'pay': p, 'min': m}
            
        render_calendar_view(summary, v_y, v_m, st.session_state.closing_day)

    # --- TAB 3: 設定 ---
    with tabs[2]:
        st.write("")
        st.subheader("設定")
        c1, c2, c3 = st.columns(3)
        nw = c1.number_input("基本時給", value=st.session_state.base_wage, step=10)
        ndw = c2.number_input("運転時給", value=st.session_state.wage_drive, step=10)
        ncd = c3.number_input("締め日", value=st.session_state.closing_day, min_value=1, max_value=31)
        
        if st.button("保存"):
            st.session_state.base_wage = nw
            st.session_state.wage_drive = ndw
            st.session_state.closing_day = ncd
            save_setting('base_wage', nw, st.session_state.user_id)
            save_setting('wage_drive', ndw, st.session_state.user_id)
            save_setting('closing_day', ncd, st.session_state.user_id)
            st.success("保存しました")
            st.rerun()

        st.markdown("<br><h6>アカウント変更</h6>", unsafe_allow_html=True)
        with st.form("act_change"):
            nid = st.text_input("新ID", value=st.session_state.user_id)
            npw = st.text_input("新PW", type="password")
            cpw = st.text_input("現在のパスワード", type="password")
            if st.form_submit_button("更新"):
                users = load_auth_users()
                if cpw != users.get(st.session_state.user_id, ""): st.error("現在のパスワードが違います")
                elif not re.search(r'[a-zA-Z]', nid): st.error("IDに英字を含めてください")
                elif npw and (not re.search(r'[a-zA-Z]', npw) or not re.search(r'\d', npw)): st.error("PWは英数混在必須です")
                elif nid != st.session_state.user_id and nid in users: st.error("ID重複")
                else:
                    update_user_id_across_sheets(st.session_state.user_id, nid, npw or cpw, users)
                    st.session_state.user_id = nid
                    st.success("更新しました")
                    st.rerun()
        
    # --- TAB 4: 管理者 ---
    if is_admin:
        with tabs[3]:
            st.title("管理者")
            st.subheader("アカウント一覧")
            df_set = conn.read(worksheet="settings", ttl=0)
            key_df = df_set[df_set['key'].str.endswith(('_id', '_pw'))].copy()
            if not key_df.empty:
                ids = key_df[key_df['key'].str.endswith('_id')]
                pws = key_df[key_df['key'].str.endswith('_pw')]
                disp = []
                for _, r in ids.iterrows():
                    u_id = r['value']
                    pw_r = pws[pws['key'] == r['key'].replace('_id', '_pw')]
                    u_pw = pw_r.iloc[0]['value'] if not pw_r.empty else ""
                    disp.append({"ID": u_id, "PW": u_pw})
                st.dataframe(pd.DataFrame(disp), use_container_width=True)

            st.subheader("新規作成")
            with st.form("create_user"):
                new_id = st.text_input("ID")
                new_pw = st.text_input("PW", type="password")
                if st.form_submit_button("作成"):
                    if not re.search(r'[a-zA-Z]', new_id): st.error("IDに英字必須")
                    elif not re.search(r'[a-zA-Z]', new_pw) or not re.search(r'\d', new_pw): st.error("PWは英数混在")
                    elif new_id in load_auth_users(): st.error("重複")
                    else:
                        n = get_next_user_number(df_set)
                        save_setting(f'user_{n}_id', new_id)
                        save_setting(f'user_{n}_pw', new_pw)
                        st.success("作成完了")
                        st.rerun()