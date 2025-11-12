using System.Globalization;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Azure.Storage.Blobs;
using CsvHelper;
using NedVision.Api.Models;

var builder = WebApplication.CreateBuilder(args);

// 🔹 Azure Blob (data source)
const string AzureBlobConnectionString = "secret";
const string containerName = "secret";
const string blobName = "secret";

// 🔹 DeepSeek API
const string DeepSeekEndpoint = "secret";
const string DeepSeekApiKey = "secret";
const string DeepSeekModel = "secret";

// Swagger + CORS (dev-friendly)
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy => policy
        .AllowAnyHeader()
        .AllowAnyMethod()
        .AllowCredentials()
        .SetIsOriginAllowed(_ => true) // dev-only
    );
});

// HttpClient to talk to Python
builder.Services.AddHttpClient("analytics", client =>
{
    var baseUrl = builder.Configuration["Analytics:BaseUrl"] ?? "https://localhost:8000";
    client.BaseAddress = new Uri(baseUrl);
});

var app = builder.Build();

app.UseCors();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.MapGet("/health", () => Results.Ok(new { status = "ok", service = "NedVision.Api" }));

// Proxies
app.MapPost("/api/forecast", async (ForecastRequest req, IHttpClientFactory httpFactory, ILoggerFactory lf) =>
{
    var log = lf.CreateLogger("ForecastProxy");
    var client = httpFactory.CreateClient("analytics");

    log.LogInformation("POST /forecast -> {@Req}", req);
    var resp = await client.PostAsJsonAsync("/forecast", req);
    var body = await resp.Content.ReadAsStringAsync();
    log.LogInformation("Analytics status {Status} body: {Body}", (int)resp.StatusCode, body);

    if (!resp.IsSuccessStatusCode)
        return Results.Problem(detail: body, statusCode: (int)resp.StatusCode, title: "Analytics error");

    return Results.Text(body, "application/json");
});


app.MapPost("/api/simulate", async (SimulationRequest req, IHttpClientFactory httpFactory) =>
{
    var client = httpFactory.CreateClient("analytics");
    var resp = await client.PostAsJsonAsync("/simulate", req);
    if (!resp.IsSuccessStatusCode)
    {
        var err = await resp.Content.ReadAsStringAsync();
        return Results.Problem(detail: err, statusCode: (int)resp.StatusCode, title: "Analytics error");
    }
    var json = await resp.Content.ReadAsStringAsync();
    return Results.Text(json, "application/json");
});

// GET /api/invoices_due?window_days=7  -> forward to analytics
app.MapGet("/api/invoices_due", async (int window_days, IHttpClientFactory http) =>
{
    var c = http.CreateClient("analytics");
    var resp = await c.GetAsync($"/invoices_due?window_days={window_days}");
    var body = await resp.Content.ReadAsStringAsync();
    return resp.IsSuccessStatusCode
        ? Results.Text(body, "application/json")
        : Results.Problem(
            detail: body,
            statusCode: (int)resp.StatusCode,
            title: "Analytics error"
        );
});

// POST /api/whatif (JSON) -> forward to analytics /whatif
app.MapPost("/api/whatif", async (WhatIfRequest req, IHttpClientFactory http) =>
{
    var c = http.CreateClient("analytics");
    var resp = await c.PostAsJsonAsync("/whatif", req);
    var body = await resp.Content.ReadAsStringAsync();
    return resp.IsSuccessStatusCode
        ? Results.Text(body, "application/json")
        : Results.Problem(detail: body, statusCode: (int)resp.StatusCode, title: "Analytics error");
});

// POST /api/whatif/upload (multipart) -> forward file to analytics /whatif/upload
app.MapPost("/api/whatif/upload", async (HttpRequest httpReq, IHttpClientFactory http) =>
{
    if (!httpReq.HasFormContentType) return Results.BadRequest("multipart/form-data required");
    var form = await httpReq.ReadFormAsync();
    var file = form.Files["file"];
    if (file is null || file.Length == 0) return Results.BadRequest("file is required");

    using var ms = new MemoryStream();
    await file.CopyToAsync(ms);
    ms.Position = 0;

    using var content = new MultipartFormDataContent();
    var fileContent = new StreamContent(ms);
    fileContent.Headers.ContentType = new MediaTypeHeaderValue("text/csv");
    content.Add(fileContent, "file", file.FileName);

    var c = http.CreateClient("analytics");
    var resp = await c.PostAsync("/whatif/upload", content);
    var body = await resp.Content.ReadAsStringAsync();
    return resp.IsSuccessStatusCode
        ? Results.Text(body, "application/json")
        : Results.Problem(
        detail: body,
        statusCode: (int)resp.StatusCode,
        title: "Analytics error"
    );
});

app.MapGet("/api/debit_orders_due", async (string branch, int window_days, IHttpClientFactory http) =>
{
    var c = http.CreateClient("analytics");
    var url = $"/debit_orders_due?branch={Uri.EscapeDataString(branch)}&window_days={window_days}";
    var resp = await c.GetAsync(url);
    var body = await resp.Content.ReadAsStringAsync();
    return resp.IsSuccessStatusCode
        ? Results.Text(body, "application/json")
        : Results.Problem(detail: body, statusCode: (int)resp.StatusCode, title: "Analytics error");
});

// --- Read Blob ---
app.MapGet("/api/blob/read", async (ILoggerFactory loggerFactory) =>
{
    var log = loggerFactory.CreateLogger("BlobReader");
    try
    {
        var blobClient = new BlobClient(AzureBlobConnectionString, containerName, blobName);
        if (!await blobClient.ExistsAsync())
            return Results.NotFound(new { error = $"Blob '{blobName}' not found in '{containerName}'." });

        var download = await blobClient.DownloadContentAsync();
        var csvContent = download.Value.Content.ToString();

        using var reader = new StringReader(csvContent);
        using var csv = new CsvReader(reader, CultureInfo.InvariantCulture);
        var records = csv.GetRecords<dynamic>().ToList();

        var simplified = records.Select(r => new
        {
            Date = r.Date,
            Account = r.Account,
            Description = r.Description,
            Debit_ZAR = TryParseDecimal(r.Debit_ZAR),
            Credit_ZAR = TryParseDecimal(r.Credit_ZAR),
            Balance_ZAR = TryParseDecimal(r.Balance_ZAR)
        });

        return Results.Json(simplified);
    }
    catch (Exception ex)
    {
        log.LogError(ex, "Error reading blob");
        return Results.Problem($"Error reading blob: {ex.Message}");
    }
});

// --- AI Insights Endpoint ---
app.MapGet("/api/insights", async (ILoggerFactory loggerFactory) =>
{
    var log = loggerFactory.CreateLogger("AIInsights");
    try
    {
        var data = await ReadBlobDataAsync();
        if (data == null)
            return Results.NotFound(new { error = "Blob not found or empty." });

        var prompt = new StringBuilder();
        prompt.AppendLine("You are an AI financial analyst for a cashflow dashboard.");
        prompt.AppendLine("Analyze the following 30 days of transaction data and return strictly valid JSON with exactly three short insights:");
        prompt.AppendLine(@"
{
  ""Opportunity"": ""Positive financial observation"",
  ""Warning"": ""Cautionary observation"",
  ""Risk"": ""Potential risk observation""
}");
        prompt.AppendLine("Each value must be under 25 words. Be concise and factual.");
        prompt.AppendLine("Here is the data:");
        prompt.AppendLine(data);

        var responseJson = await QueryDeepSeekAsync(prompt.ToString());
        if (responseJson is not null)
            return Results.Json(responseJson);
        else
            return Results.Problem("Unable to parse DeepSeek response as JSON.");
    }
    catch (Exception ex)
    {
        log.LogError(ex, "AI insight error");
        return Results.Problem($"AI Insight generation failed: {ex.Message}");
    }
});

// --- "What If" POST (JSON Body) ---
app.MapPost("/api/prompt-insight", async (HttpRequest request, ILoggerFactory loggerFactory) =>
{
    var log = loggerFactory.CreateLogger("AIWhatIf");

    try
    {
        // ✅ Read JSON body
        using var reader = new StreamReader(request.Body);
        var bodyText = await reader.ReadToEndAsync();

        if (string.IsNullOrWhiteSpace(bodyText))
            return Results.BadRequest(new { error = "Please provide a JSON body like { \"scenario\": \"What if sales drop by 15% next week?\" }" });

        // ✅ Parse JSON
        JsonElement jsonBody;
        try
        {
            jsonBody = JsonSerializer.Deserialize<JsonElement>(bodyText);
        }
        catch
        {
            return Results.BadRequest(new { error = "Invalid JSON body." });
        }

        // ✅ Extract scenario
        var scenario = jsonBody.TryGetProperty("scenario", out var s) ? s.GetString() : null;
        if (string.IsNullOrWhiteSpace(scenario))
            return Results.BadRequest(new { error = "Missing 'scenario' field in request body." });

        // ✅ Read local CSV
        var data = await ReadLocalCsvAsync();
        if (data == null)
            return Results.NotFound(new { error = "Local CSV file not found or empty." });

        // ✅ Build prompt
        var prompt = new StringBuilder();
        prompt.AppendLine("You are an AI financial analyst for a cashflow dashboard.");
        prompt.AppendLine("Given the 30 days of transaction data and the user's scenario, return only the potential financial impact in valid JSON.");
        prompt.AppendLine("The response must follow this structure:");
        prompt.AppendLine(@"
{
  ""Impact"": ""Brief description of the potential financial impact (max 25 words).""
}");
        prompt.AppendLine("NO markdown, no backticks, no commentary.");
        prompt.AppendLine();
        prompt.AppendLine("User Scenario: " + scenario);
        prompt.AppendLine("Here is the data:");
        prompt.AppendLine(data);

        // ✅ Send to DeepSeek
        var responseJson = await QueryDeepSeekAsync(prompt.ToString());
        if (responseJson is not null)
            return Results.Json(responseJson);

        return Results.Problem("Unable to parse DeepSeek 'What If' response as JSON.");
    }
    catch (Exception ex)
    {
        log.LogError(ex, "WhatIf generation error");
        return Results.Problem($"What-If scenario generation failed: {ex.Message}");
    }

    return Results.Problem("Unhandled error occurred while generating What-If analysis.");
});

// --- Helper Methods ---
async Task<string?> ReadLocalCsvAsync()
{
    try
    {
        var filePath = Path.Combine(Directory.GetCurrentDirectory(), "data", "Full_Consolidated_Monthly_Data__30_Days_.csv");

        if (!File.Exists(filePath))
            return null;

        var csvContent = await File.ReadAllTextAsync(filePath);

        using var reader = new StringReader(csvContent);
        using var csv = new CsvReader(reader, CultureInfo.InvariantCulture);
        var records = csv.GetRecords<dynamic>().ToList();

        var sampleData = records.Take(30).Select(r => new
        {
            date = r.Date,
            account = r.Account,
            description = r.Description,
            debit_ZAR = r.Debit_ZAR,
            credit_ZAR = r.Credit_ZAR,
            balance_ZAR = r.Balance_ZAR
        }).ToList();

        var json = JsonSerializer.Serialize(sampleData);
        return json.Length > 8000 ? json[..8000] + "..." : json;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"❌ Error reading local CSV: {ex.Message}");
        return null;
    }
}

// --- AI Insights Endpoint ---
app.MapGet("/api/risk-insights", async (ILoggerFactory loggerFactory) =>
{
    var log = loggerFactory.CreateLogger("AIInsights");
    try
    {
        var data = await ReadLocalCsvAsync();
        if (data == null)
            return Results.NotFound(new { error = "Local CSV file not found or empty." });

        var prompt = new StringBuilder();
        prompt.AppendLine("You are an AI financial analyst for a cashflow dashboard.");
        prompt.AppendLine("Analyze the following 30 days of transaction data and return strictly valid JSON with exactly three short insights:");
        prompt.AppendLine(@"
{
  ""Opportunity"": ""Positive financial observation"",
  ""Warning"": ""Cautionary observation"",
  ""Risk"": ""Potential risk observation""
}");
        prompt.AppendLine("Each value must be under 25 words. Be concise and factual.");
        prompt.AppendLine("Here is the data:");
        prompt.AppendLine(data);

        var responseJson = await QueryDeepSeekAsync(prompt.ToString());
        if (responseJson is not null)
            return Results.Json(responseJson);
        else
            return Results.Problem("Unable to parse DeepSeek response as JSON.");
    }
    catch (Exception ex)
    {
        log.LogError(ex, "AI insight error");
        return Results.Problem($"AI Insight generation failed: {ex.Message}");
    }
});

// --- Helper Methods ---
async Task<string?> ReadBlobDataAsync()
{
    var blobClient = new BlobClient(AzureBlobConnectionString, containerName, blobName);
    if (!await blobClient.ExistsAsync())
        return null;

    var download = await blobClient.DownloadContentAsync();
    var csvContent = download.Value.Content.ToString();

    using var reader = new StringReader(csvContent);
    using var csv = new CsvReader(reader, CultureInfo.InvariantCulture);
    var records = csv.GetRecords<dynamic>().ToList();

    var sampleData = records.Take(30).Select(r => new
    {
        date = r.Date,
        account = r.Account,
        description = r.Description,
        debit_ZAR = r.Debit_ZAR,
        credit_ZAR = r.Credit_ZAR,
        balance_ZAR = r.Balance_ZAR
    }).ToList();

    var json = JsonSerializer.Serialize(sampleData);
    return json.Length > 8000 ? json[..8000] + "..." : json;
}

async Task<JsonElement?> QueryDeepSeekAsync(string prompt)
{
    using var httpClient = new HttpClient();
    httpClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", DeepSeekApiKey);

    var body = new
    {
        model = DeepSeekModel,
        prompt = prompt,
        max_tokens = 300,
        temperature = 0.6
    };

    var jsonContent = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
    var response = await httpClient.PostAsync(DeepSeekEndpoint, jsonContent);
    var raw = await response.Content.ReadAsStringAsync();

    if (!response.IsSuccessStatusCode)
        return null;

    using var doc = JsonDocument.Parse(raw);
    var text = doc.RootElement.GetProperty("choices")[0].GetProperty("text").GetString()?.Trim();

    if (string.IsNullOrWhiteSpace(text))
        return null;

    var parsed = TryCleanAndParseJson(text);
    return parsed;
}

static JsonElement? TryCleanAndParseJson(string raw)
{
    try
    {
        var cleaned = raw
            .Replace("```json", "")
            .Replace("```", "")
            .Trim()
            .Replace("\\n", "\n");

        return JsonSerializer.Deserialize<JsonElement>(cleaned);
    }
    catch
    {
        return null;
    }
}

decimal TryParseDecimal(object? value)
{
    if (value == null) return 0;
    return decimal.TryParse(value.ToString(), out var result) ? result : 0;
}


app.Run();

// Proxy request shapes
record ForecastRequest(string branch, DateOnly? from_date, DateOnly? to_date, int horizon_days = 30, List<string>? files = null);
record Adjustment(DateOnly date, decimal delta, string? label);
record SimulationRequest(string branch, DateOnly? base_from_date, DateOnly? base_to_date, int horizon_days = 30, List<string>? files = null, List<Adjustment>? adjustments = null);

