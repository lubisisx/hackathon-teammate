# -----------------------
# Stage 1: Build
# -----------------------
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

# Copy project files and restore dependencies
COPY ["NedVision.Api/NedVision.Api.csproj", "NedVision.Api/"]
COPY ["NedVision.Domain/NedVision.Domain.csproj", "NedVision.Domain/"]
COPY ["NedVision.Infrastructure/NedVision.Infrastructure.csproj", "NedVision.Infrastructure/"]
RUN dotnet restore "NedVision.Api/NedVision.Api.csproj"

# Copy the rest of the source code
COPY ["NedVision.Api/", "NedVision.Api/"]
COPY ["NedVision.Domain/", "NedVision.Domain/"]
COPY ["NedVision.Infrastructure/", "NedVision.Infrastructure/"]

# Build and publish
RUN dotnet publish "NedVision.Api/NedVision.Api.csproj" -c Release -o /app/publish

# -----------------------
# Stage 2: Runtime
# -----------------------
FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS final
WORKDIR /app

COPY --from=build /app/publish .

EXPOSE 8080
ENTRYPOINT ["dotnet", "NedVision.Api.dll"]
