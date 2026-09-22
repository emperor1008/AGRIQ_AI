/** Shared API payload types (kept in sync with agriq/schemas). */

export type WeatherBadge = "LIVE SYNC" | "OFFLINE FALLBACK";

export interface WeatherConsole {
  district: string;
  live_badge: WeatherBadge;
  updated_at: string;
  source_note: string;
  soil_water_note: string;
  current: {
    temp: number;
    humidity: number;
    rain: number;
    wind: number;
    condition: string;
    time: string;
  };
  daily: Array<{
    day: string;
    temp_max: number;
    temp_min: number;
    rain: number;
    pop: number;
    wind: number;
    condition: string;
  }>;
  field_alert: string;
  disease_window: string;
  irrigation_note: string;
  spray_window: string;
}

export interface RiskForecastRow {
  day: string;
  temp: number;
  humidity: number;
  rain: number;
  risk: number;
  status: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  color: string;
}

export interface LiveWeatherResponse {
  weather_console: WeatherConsole;
  risk_forecast: RiskForecastRow[];
}

export interface AskAiResponse {
  answer: string;
  ok: boolean;
  source: "gemini" | "knowledge_engine";
}
