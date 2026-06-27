# yfinance-risk-analysis

`yfinance-risk-analysis`는 Yahoo Finance와 FRED 데이터를 이용해 금융시장 위험도를 모니터링하는 Python Dash 대시보드입니다. 변동성, 신용위험, 미국 국채금리, 유동성, 글로벌 위험자산 흐름을 한 화면에서 확인하고, 이를 바탕으로 시장 스트레스 점수와 레짐을 계산합니다.

## 주요 기능

- `yfinance`로 VIX, VIX3M, VIX6M, VXN, SKEW, HYG, JNK, LQD, UUP, SHY, IEI, EEM 등 시장 데이터를 다운로드합니다.
- `fredapi`로 미국 금리, 하이일드 스프레드, 머니마켓펀드, 역레포, M2, 준비금 관련 데이터를 가져옵니다.
- 변동성, 신용위험, 유동성, 금리 스프레드, 글로벌 위험 지표를 Plotly 차트로 시각화합니다.
- 여러 위험 지표의 z-score를 합성해 `Stress Score`를 계산합니다.
- 유동성, 신용위험, 변동성, 글로벌 위험자산 흐름을 종합해 `risk_on`, `neutral`, `caution`, `risk_off`, `crisis` 레짐을 분류합니다.
- 일별 레짐 스냅샷을 SQLite 파일에 저장해 과거 레짐 정확도와 스트레스 이후 수익률을 분석합니다.
- 선택적으로 Telegram 알림을 보낼 수 있습니다.

## 프로젝트 구조

```text
yfinance-risk-analysis/
├── app.py                         # Dash 앱 진입점
├── layout.py                      # 화면 레이아웃과 탭 구성
├── callbacks.py                   # 탭별 데이터 처리, 차트 출력, 스냅샷 저장, 알림 처리
├── data_fetching.py               # Yahoo Finance, FRED, Stooq 데이터 수집 및 캐시 처리
├── indicators.py                  # z-score, HYG/LQD, Stress Score, 스프레드 계산
├── regime.py                      # 시장 레짐 feature 생성과 레짐 분류
├── figures.py                     # Plotly 차트 생성 함수
├── snapshot_store.py              # SQLite 스냅샷 저장소
├── snapshot_history.py            # 저장된 스냅샷 조회
├── research_metrics.py            # 레짐 정확도와 forward return 분석
├── research_utils.py              # 벤치마크 가격과 스냅샷 병합 유틸
├── telegram_utils.py              # Telegram 알림 유틸
├── requirements.txt               # Python 의존성
├── .env.example                   # 환경변수 예시
├── data/                          # FRED 캐시와 SQLite 스냅샷 저장 위치
└── excel_file/                    # 일부 계산 결과 Excel 출력 위치
```

## 실행 방법

### 1. 저장소 클론

```bash
git clone https://github.com/<your-github-id>/yfinance-risk-analysis.git
cd yfinance-risk-analysis
```

### 2. 가상환경 생성

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS 또는 Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. 패키지 설치

```bash
pip install -r requirements.txt
```

### 4. 환경변수 설정

프로젝트 루트에 `.env` 파일을 만들고 필요한 값을 입력합니다.

```env
FRED_API_KEY=your_fred_key_here
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

`FRED_API_KEY`는 FRED 데이터를 가져오기 위해 필요합니다. Telegram 알림을 사용하지 않는다면 `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`는 비워 두어도 됩니다.

FRED API Key는 [FRED API 문서](https://fred.stlouisfed.org/docs/api/api_key.html)에서 발급할 수 있습니다.

### 5. 앱 실행

```bash
python app.py
```

실행 후 브라우저에서 아래 주소로 접속합니다.

```text
http://localhost:8050
```

`app.py`는 기본적으로 다음 설정으로 Dash 서버를 실행합니다.

```python
app.run(host="0.0.0.0", port=8050, debug=True)
```

## 대시보드 탭 설명

### Stress Score

VIX, VIX3M, VIX6M, HYG/LQD, TNX, UUP, EEM 등의 z-score를 가중합해 종합 시장 스트레스 점수를 계산합니다. 점수가 높을수록 시장 스트레스가 큰 상태로 해석합니다.

### Volatility

`^VIX`, `^VIX3M`, `^VIX6M`, `^VXN`, `^SKEW`를 이용해 변동성과 꼬리위험을 확인합니다.

### Liquidity

FRED의 `WRMFNS`, `RRPONTSYD`, `M2SL`, `TOTRESNS`, `WRESBAL` 데이터를 이용해 미국 유동성 흐름을 z-score로 변환합니다. 여러 유동성 지표를 합성해 `LiquidityScore`도 계산합니다.

### Credit Risk

`HYG`, `JNK`, `LQD`, FRED의 하이일드 OAS 데이터, 그리고 `HYG/LQD` 비율을 이용해 신용위험을 분석합니다.

### Treasury Yields

Yahoo Finance의 `^FVX`, `^TNX`, `^TYX`와 FRED 금리 데이터를 이용해 미국 금리 흐름을 시각화합니다.

### 3mo-2y Spread / 3mo-10y Spread

FRED의 3개월, 2년, 10년 국채금리를 이용해 장단기 금리차를 계산합니다. 금리차가 0 이하로 내려가면 경기침체 우려 신호로 해석될 수 있습니다.

### Global Liquidity

`UUP`, `SHY`, `IEI` 등을 통해 달러 강세와 글로벌 유동성 환경을 관찰합니다. 일반적으로 달러 강세는 글로벌 유동성 긴축 신호로 볼 수 있습니다.

### Global Risk (EEM)

`EEM`을 이용해 신흥국 주식의 위험선호 흐름과 drawdown을 확인합니다.

### Regime Monitor

`regime.py`에서 생성한 feature를 바탕으로 현재 시장 레짐을 분류합니다.

- `risk_on`: 위험자산에 우호적인 환경
- `neutral`: 중립적인 환경
- `caution`: 주의가 필요한 환경
- `risk_off`: 위험 회피 환경
- `crisis`: 위기 국면

레짐별로 포지션 허용 여부와 포지션 크기 배수(`size_mult`)도 함께 계산합니다.

### Historical Regime Accuracy

저장된 레짐 스냅샷과 벤치마크 가격을 결합해 과거 레짐이 이후 수익률과 얼마나 잘 연결되었는지 분석합니다.

### Stress vs Forward Returns

과거 Stress Score 수준과 이후 수익률의 관계를 확인합니다. 스트레스가 높았던 구간 이후 시장 수익률이 어떻게 변했는지 분석하는 용도입니다.

## 프로그램 동작 흐름

1. `app.py`가 Dash 앱을 생성하고 `layout.py`에서 화면 구조를 불러옵니다.
2. `callbacks.py`가 Dash callback을 등록합니다.
3. 앱이 로드되거나 15분마다 `dcc.Interval`이 실행되면 `fetch_data()`가 데이터를 새로 가져옵니다.
4. `data_fetching.py`는 Yahoo Finance 가격 데이터와 FRED 매크로 데이터를 병합합니다.
5. `indicators.py`는 z-score, 금리 스프레드, 신용 비율, Stress Score를 계산합니다.
6. `regime.py`는 유동성, 신용위험, 변동성, 글로벌 위험 지표를 이용해 시장 레짐을 분류합니다.
7. `figures.py`는 계산된 데이터를 Plotly 차트로 변환합니다.
8. `callbacks.py`는 선택된 탭에 맞는 차트와 최근 3개월 테이블을 화면에 표시합니다.
9. `snapshot_store.py`는 일별 레짐 스냅샷을 `data/risk_snapshots.sqlite`에 저장합니다.

## 핵심 계산 방식

### Z-score

각 지표는 평균에서 얼마나 벗어나 있는지 보기 위해 z-score로 변환됩니다.

```text
z-score = (현재값 - 평균) / 표준편차
```

일부 지표는 전체 기간 기준 z-score를 쓰고, 레짐 계산에는 관측치 기준 rolling z-score를 주로 사용합니다.

### Stress Score

`indicators.py`의 `compute_stress_score()`는 다음 지표를 가중합합니다.

```text
^VIX     : 0.30
^VIX3M   : 0.15
^VIX6M   : 0.10
HYG/LQD  : 0.25
^TNX     : 0.15
UUP      : 0.05
EEM      : -0.10
```

사용 가능한 컬럼만 계산에 포함됩니다.

### Regime Score

`regime.py`는 유동성 점수, 하이일드 스프레드, HYG/LQD, VIX, Stress Score, EEM, UUP, 금리 스프레드, VIX term structure를 조합해 `regime_score`를 만듭니다. 점수가 높을수록 시장 환경이 우호적이고, 점수가 낮을수록 위험 회피 환경에 가깝습니다.

## 데이터와 캐시

- FRED 데이터는 `data/fred_cache/` 아래 CSV로 캐시됩니다.
- 일별 레짐 스냅샷은 `data/risk_snapshots.sqlite`에 저장됩니다.
- 레짐 분류 결과 일부는 `excel_file/out_classify_regime.xlsx`로 출력됩니다.

이 파일들은 실행 중 자동으로 생성될 수 있습니다.

## 테스트 실행

프로젝트에는 일부 계산 로직에 대한 테스트 파일이 포함되어 있습니다.

```bash
python -m pytest
```

만약 `pytest`가 설치되어 있지 않다면 다음 명령으로 설치합니다.

```bash
pip install pytest
```

## 배포 메모

`requirements.txt`에는 `gunicorn`이 포함되어 있어 Render, Railway, Fly.io 같은 서비스에서 배포할 수 있습니다. 배포 환경에서는 반드시 `FRED_API_KEY`를 환경변수로 등록해야 합니다.

예시 실행 명령:

```bash
gunicorn app:server
```

현재 `app.py`에는 `app = Dash(...)`만 정의되어 있으므로, 배포 플랫폼에서 `server` 객체를 요구한다면 아래 한 줄을 추가해야 합니다.

```python
server = app.server
```

## 주의사항

- 이 프로젝트는 투자 판단을 돕기 위한 분석 도구이며, 매수나 매도 추천을 제공하지 않습니다.
- Yahoo Finance와 FRED 데이터는 제공처의 사정에 따라 지연, 누락, 형식 변경이 발생할 수 있습니다.
- FRED API 호출 제한에 걸릴 수 있으므로 캐시를 활용합니다.
- 레짐 분류와 Stress Score는 모델 기반 지표이며 실제 시장 결과를 보장하지 않습니다.

