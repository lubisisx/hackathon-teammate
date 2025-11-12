import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ApiService, ForecastResponse } from '../../core/api.service';
import { ForecastChartComponent, Point } from '../../shared/forecast-chart';

type DebitOrderItem = { customer: string; amount: number; dueLabel: string };
type InvoiceItem = { client: string; amount: number; dueLabel: string; dueDate?: string; };

@Component({
  selector: 'app-dashboard-shell',
  standalone: true,
  imports: [CommonModule, HttpClientModule, FormsModule, ForecastChartComponent],
  templateUrl: './dashboard-shell.html',
  styleUrl: './dashboard-shell.scss'
})
export class DashboardShellComponent {
  private api = inject(ApiService);

  private remindersKey = 'invoiceReminders';

  data: ForecastResponse | null = null;

  currentBalance = 0;
  deltaToday = 0;
  riskNote = 'Cashflow might dip Friday';
  upcomingDebits = 0;

  debitOrdersDue: DebitOrderItem[] = [];
  invoicesDue: InvoiceItem[] = [];
  whatIfData: any[] = [];
  showWhatIf = false;

  branch = 'CPT02';
  orgUser = 'Nedbank • DemoUser';

  // slide-over state
  whatIfOpen = false;
  whatIfDate: string = '';         // yyyy-mm-dd
  whatIfDelta: number = 0;

  // ===== Slide-over toggles =====
  openWhatIf() { this.whatIfOpen = true; }
  closeWhatIf() { this.whatIfOpen = false; }

  ngOnInit() {
    this.loadForecast();
    this.checkDueRemindersNow();
  }

  remindInvoice(inv: InvoiceItem) {
    this.saveReminder(inv);
    this.scheduleTimeoutFor(inv);
    alert(`Reminder set for ${inv.client} on ${inv.dueLabel}.`);
  }

  loadForecast() {
    this.api.getForecast(this.branch, 30).subscribe(res => {
      this.data = res;

      // Current balance = last history cash
      const lastHist = res.history[res.history.length - 1];
      this.currentBalance = lastHist ? Math.round(lastHist.cash) : 0;

      // Delta today = last - prev
      const prev = res.history[res.history.length - 2];
      this.deltaToday = (lastHist && prev) ? Math.round(lastHist.cash - prev.cash) : 0;

      // Upcoming debits = sum of negative categories (absolute)
      const outflowCats = res.drivers?.top_outflows_by_category ?? {};
      const upcoming = Object.values(outflowCats).reduce((a: number, v: any) => {
        const n = Number(v) || 0;
        return n < 0 ? a + Math.abs(n) : a;
      }, 0);
      this.upcomingDebits = Math.round(upcoming);

      // Debit Orders Due by customer (derive from negative counterparties)
      // We treat counterparties with net outflow as "debit orders".
      const cps = res.drivers?.top_counterparties ?? {};
      this.debitOrdersDue = Object.entries(cps)
        .filter(([_, amt]) => Number(amt) < 0)
        .map(([name, amt]) => ({
          customer: name || 'Unknown',
          amount: Math.round(Math.abs(Number(amt) || 0)),
          dueLabel: 'Due within 7 days' // For MVP; refine when backend exposes dates
        }))
        .sort((a, b) => b.amount - a.amount)
        .slice(0, 5);

      // Invoices Due (placeholder until backend endpoint available)
      // Keep the structure ready so you can swap in real data later.
      // Fetch invoices due (7-day window)
      this.api.getInvoicesDue(7).subscribe(resp => {
        const paid = JSON.parse(localStorage.getItem('paidInvoices') || '[]') as string[];
        const mapped = resp.items.map(it => ({
          client: it.client,
          amount: it.amount,
          dueLabel: it.due_label,
          dueDate: it.due_date
        }));
        this.invoicesDue = mapped.filter(inv => !paid.includes(`${inv.client}|${inv.dueDate ?? inv.dueLabel}|${inv.amount}`));
      });

      this.api.getDebitOrdersDue(7, this.branch).subscribe(resp => {
        this.debitOrdersDue = resp.items || [];
      });
    });
  }

  connectBank() { alert('Bank linking is mocked for the demo.'); }

  onUpload(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    this.api.uploadWhatIfScenario(formData).subscribe(res => {
      this.whatIfData = res.forecast || [];
      this.showWhatIf = true;
    });
  }

  runWhatIf() {
    this.api.getWhatIf(this.branch, 30, { delayInvoices: 3 })
      .subscribe(res => this.whatIfData = res.forecast);
  }

  clearWhatIf() { this.whatIfData = []; this.showWhatIf = false; }

  // ===== Custom simulate (form submit) =====
  onSimulate(ev: Event) {
    ev.preventDefault();
    const d = this.whatIfDate ? new Date(this.whatIfDate) : new Date();
    const adj = [{ date: d.toISOString().slice(0, 10), delta: Number(this.whatIfDelta || 0) }];

    this.api.simulate(this.branch, adj, 30).subscribe(res => {
      // prefer adjusted path if present; fallback to generic forecast
      this.whatIfData = (res.forecast_adjusted ?? res.forecast ?? []);
      this.showWhatIf = true;
    });
  }

  // ===== Presets =====
  presetSalariesEarly() {
    // Example: next Friday large negative outflow
    const now = new Date();
    const nextFri = new Date(now);
    // find next Friday (5)
    const diff = (5 - now.getDay() + 7) % 7 || 7;
    nextFri.setDate(now.getDate() + diff);
    this.whatIfDate = nextFri.toISOString().slice(0, 10);
    this.whatIfDelta = -250000; // adjust as you like for demo
  }

  presetInvoiceLate() {
    this.api.getWhatIf(this.branch, 30, { delayInvoices: 3 })
      .subscribe(res => {
        this.whatIfData = res.forecast || [];
        this.showWhatIf = true;
      });
  }

  applyWhatIf() {
    this.closeWhatIf();
  }

  aiRemind() {
    // Simulate a backend call to a Notification service
    console.info('[AI] Notified relationship banker about Friday dip risk.');
    // Simple UX feedback (you can swap this for a toast)
    alert('Relationship banker notified (simulated).');
  }

  markPaid(inv: InvoiceItem) {
    this.invoicesDue = this.invoicesDue.filter(i => i !== inv);

    const paid = JSON.parse(localStorage.getItem('paidInvoices') || '[]') as string[];
    const id = `${inv.client}|${inv.dueDate ?? inv.dueLabel}|${inv.amount}`;
    if (!paid.includes(id)) {
      paid.push(id);
      localStorage.setItem('paidInvoices', JSON.stringify(paid));
    }
  }

  private saveReminder(inv: InvoiceItem) {
    const list = JSON.parse(localStorage.getItem(this.remindersKey) || '[]') as InvoiceItem[];
    // avoid duplicates by using client + dueDate + amount
    const exists = list.some(x => x.client === inv.client && (x.dueDate ?? x.dueLabel) === (inv.dueDate ?? inv.dueLabel) && x.amount === inv.amount);
    if (!exists) {
      list.push(inv);
      localStorage.setItem(this.remindersKey, JSON.stringify(list));
    }
  }

  private checkDueRemindersNow() {
    const list = JSON.parse(localStorage.getItem(this.remindersKey) || '[]') as InvoiceItem[];
    const todayIso = new Date().toISOString().slice(0, 10);
    const dueToday = list.filter(x => (x.dueDate ?? '').slice(0, 10) === todayIso);
    if (dueToday.length) {
      const lines = dueToday.map(x => `• ${x.client} — R ${x.amount.toLocaleString('en-ZA')} (due today)`).join('\n');
      alert(`Invoice reminders:\n${lines}`);
      // clear today's to avoid spamming
      const remain = list.filter(x => (x.dueDate ?? '').slice(0, 10) !== todayIso);
      localStorage.setItem(this.remindersKey, JSON.stringify(remain));
    }
  }

  private scheduleTimeoutFor(inv: InvoiceItem) {
    if (!inv.dueDate) return; // can’t schedule precisely without ISO date
    const due = new Date(inv.dueDate);
    // fire at 09:00 local on due date
    due.setHours(9, 0, 0, 0);
    const ms = due.getTime() - Date.now();
    if (ms > 0 && ms < 31 * 24 * 3600 * 1000) {
      setTimeout(() => {
        alert(`Reminder: ${inv.client} — R ${inv.amount.toLocaleString('en-ZA')} is due today.`);
        // remove after triggering
        const list = JSON.parse(localStorage.getItem(this.remindersKey) || '[]') as InvoiceItem[];
        const remain = list.filter(x => !(x.client === inv.client && x.amount === inv.amount && x.dueDate === inv.dueDate));
        localStorage.setItem(this.remindersKey, JSON.stringify(remain));
      }, ms);
    }
  }

}
