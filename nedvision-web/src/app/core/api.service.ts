import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

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
    baseUrl = 'https://localhost:5000'; // .NET API

    getForecast(branch: string, horizonDays = 30) {
        return this.http.post<ForecastResponse>(`${this.baseUrl}/api/forecast`, { branch, horizon_days: horizonDays });
    }

    simulate(branch: string, adjustments: Adjustment[], horizonDays = 30) {
        return this.http.post<any>(`${this.baseUrl}/api/simulate`, { branch, horizon_days: horizonDays, adjustments });
    }

    getInvoicesDue(windowDays = 7) {
        return this.http.get<{ window_days: number; items: Array<{ invoice_no: string; client: string; amount: number; due_date: string; due_label: string }> }>(
            `${this.baseUrl}/api/invoices_due?window_days=${windowDays}` // call analytics directly if exposed
        );
        // If you prefer proxy via .NET, add a /api/invoices_due there and forward it.
    }

    getWhatIf(branch: string, horizonDays: number, params: any): Observable<any> {
        const body = {
            branch,
            horizon_days: horizonDays,
            delay_invoices: params.delayInvoices ?? 0,
            early_salaries: params.earlySalaries ?? 0,
            adjustment: params.adjustment ?? 0
        };

        return this.http.post(`${this.baseUrl}/api/whatif`, body);
    }

    uploadWhatIfScenario(formData: FormData): Observable<any> {
        return this.http.post(`${this.baseUrl}/api/whatif/upload`, formData);
    }

    getDebitOrdersDue(windowDays = 7, branch = 'CPT02') {
        return this.http.get<{ items: Array<{ customer: string; amount: number; dueLabel: string }> }>(
            `${this.baseUrl}/api/debit_orders_due?branch=${branch}&window_days=${windowDays}`
        );
    }

}
