using System.Net.Http.Json;

var builder = WebApplication.CreateBuilder(args);

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
    var baseUrl = builder.Configuration["Analytics:BaseUrl"] ?? "http://localhost:8000";
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

app.Run();

// Proxy request shapes
record ForecastRequest(string branch, DateOnly? from_date, DateOnly? to_date, int horizon_days = 30, List<string>? files = null);
record Adjustment(DateOnly date, decimal delta, string? label);
record SimulationRequest(string branch, DateOnly? base_from_date, DateOnly? base_to_date, int horizon_days = 30, List<string>? files = null, List<Adjustment>? adjustments = null);

