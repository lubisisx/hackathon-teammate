import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export interface ForecastPoint { date: string; cash: number; }
export interface ForecastResponse {
    branch: string;
    history: ForecastPoint[];
    forecast: ForecastPoint[];
    drivers: any;
}
export interface Adjustment { date: string; delta: number; label?: string; }

@Injectable({ providedIn: 'root' })
export class ApiService {
    private http = inject(HttpClient);
    baseUrl = 'http://localhost:5000'; // .NET API

    getForecast(branch: string, horizonDays = 30) {
        return this.http.post<ForecastResponse>(`${this.baseUrl}/api/forecast`, { branch, horizon_days: horizonDays });
    }

    simulate(branch: string, adjustments: Adjustment[], horizonDays = 30) {
        return this.http.post<any>(`${this.baseUrl}/api/simulate`, { branch, horizon_days: horizonDays, adjustments });
    }
}
