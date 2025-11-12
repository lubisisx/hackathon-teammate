using System.Text.Json.Serialization;

namespace NedVision.Api.Models
{
    public class WhatIfRequest
    {
        [JsonPropertyName("branch")]
        public string Branch { get; set; } = string.Empty;

        [JsonPropertyName("horizon_days")]
        public int HorizonDays { get; set; } = 30;

        [JsonPropertyName("delay_invoices")]
        public int DelayInvoices { get; set; } = 0;

        [JsonPropertyName("early_salaries")]
        public int EarlySalaries { get; set; } = 0;

        [JsonPropertyName("adjustment")]
        public decimal Adjustment { get; set; } = 0;
    }
}
