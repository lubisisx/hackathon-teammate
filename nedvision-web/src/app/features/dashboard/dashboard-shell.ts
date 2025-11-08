import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ApiService, ForecastResponse } from '../../core/api.service';
import { RouterLink } from '@angular/router';
import { ForecastChartComponent } from '../../shared/forecast-chart';

@Component({
  selector: 'app-dashboard-shell',
  standalone: true,
  imports: [CommonModule, HttpClientModule, FormsModule, ForecastChartComponent, RouterLink],
  template: `
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="brand">
        <div class="logo">
          <img src="../assets/nedbank-logo.svg" width="28" height="28" class="me-2" alt="" />
        </div>
        <strong>NedVision</strong> – Cashflow Copilot
      </div>
      <div class="badge">⚡ Azure Foundry</div>
    </div>

    <!-- Top cards -->
    <div class="grid">
      <!-- Current balance -->
      <div class="card">
        <h3>Current Balance</h3>
        <div class="value mono">R {{ (currentBalance || 0) | number:'1.0-0' }}</div>
        <div class="statline">↑ R {{ (deltaToday || 0) | number:'1.0-0' }} today</div>
        <div style="height:8px"></div>
        <span class="chip" *ngIf="riskNote">{{ riskNote }}</span>
        <div style="height:10px"></div>
        <button class="btn" (click)="connectBank()">Connect bank</button>
      </div>

      <!-- Upcoming -->
      <div class="card">
        <h3>Upcoming Debit Orders</h3>
        <div class="value mono">R {{ (upcomingDebits || 0) | number:'1.0-0' }}</div>
        <div class="small">Next 7 days</div>
        <hr style="border:none;border-top:1px solid var(--border);margin:12px 0">
        <div class="value mono">0</div>
        <div class="small">Invoices Due <span class="small">Within 7 days</span></div>
      </div>

      <!-- Insights -->
      <div class="card">
        <div class="panel-head">
          <h3>Insights</h3>
          <div class="badge">AI</div>
        </div>
        <div class="list">
          <div class="row">
            <div>
              <strong>Friday dip risk</strong>
              <div class="small">Large debit + 2 unpaid</div>
            </div>
            <div class="actions">
              <button class="btn">Remind</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Forecast + Invoices -->
    <div class="split">
      <div class="card">
        <div class="panel-head">
          <h3>30-day Forecast</h3>
          <a class="btn" [routerLink]="['/what-if']">View what-if</a>
        </div>

        <app-forecast-chart [history]="data?.history || []"
                            [forecast]="data?.forecast || []"></app-forecast-chart>

        <div class="panel-foot">
          <input type="file" #file (change)="onUpload(file.files)" hidden />
          <button class="btn" (click)="file.click()">Upload CSV</button>
        </div>
      </div>

      <div class="card">
        <div class="panel-head">
          <h3>Invoices Due</h3>
          <button class="btn">Add invoice</button>
        </div>

        <div class="list">
          <div class="row">
            <div>
              <div><strong>Client A</strong></div>
              <div class="chip">Due Mon 10 Nov</div>
            </div>
            <div class="actions">
              <div class="mono">R 8,500</div>
              <button class="btn">Mark paid</button>
              <button class="btn">Remind</button>
            </div>
          </div>

          <div class="row">
            <div>
              <div><strong>Client B</strong></div>
              <div class="chip">Due Tue 4 Nov</div>
            </div>
            <div class="actions">
              <div class="mono">R 9,630</div>
              <button class="btn">Mark paid</button>
              <button class="btn">Remind</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div style="text-align:center;color:var(--subtext);margin:24px 0" class="small">
      © 2025 NedVision • Angular 17+ • .NET 8 • Azure AI
    </div>
  </div>
  `,
})
export class DashboardShellComponent {
  private api = inject(ApiService);

  data: ForecastResponse | null = null;

  currentBalance = 0;
  deltaToday = 0;
  riskNote = 'Cashflow might dip Friday';
  upcomingDebits = 0;

  branch = 'CPT02';

  ngOnInit() { this.loadForecast(); }

  loadForecast() {
    this.api.getForecast(this.branch, 30).subscribe(res => {
      this.data = res;

      // Current balance = last cash value in history
      const lastHist = res.history[res.history.length - 1];
      this.currentBalance = lastHist ? Math.round(lastHist.cash) : 0;

      // Approx. delta today = last hist minus previous hist
      const prev = res.history[res.history.length - 2];
      this.deltaToday = (lastHist && prev) ? Math.round(lastHist.cash - prev.cash) : 0;

      // (Optional) derive "upcoming debits" from drivers (negative categories)
      const outflowCats = res.drivers?.top_outflows_by_category ?? {};
      const sum = Object.values(outflowCats).reduce((a: number, v: any) => a + Math.abs(Number(v) || 0), 0);
      this.upcomingDebits = Math.round(sum);
    });
  }

  connectBank() { alert('Bank linking is mocked for the demo.'); }

  onUpload(files: FileList | null) {
    if (!files || files.length === 0) { return; }
    // For the hackathon demo, this UX element is non-functional backend-wise.
    alert(`Uploaded ${files[0].name} (demo only)`);
  }
}
