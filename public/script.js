// Weather E-Ink Display Script - Monochrome Version

// Configuration
const API_URL = '/api/weather'; // Using the local weather server API endpoint

// DOM elements
const elements = {
    city: document.getElementById('city'),
    date: document.getElementById('date'),
    weatherIcon: document.getElementById('weather-icon'),
    temp: document.getElementById('temp'),
    feelsLike: document.getElementById('feels-like'),
    sunrise: document.getElementById('sunrise'),
    sunset: document.getElementById('sunset'),
    wind: document.getElementById('wind'),
    humidity: document.getElementById('humidity'),
    visibility: document.getElementById('visibility'),
    airQuality: document.getElementById('air-quality'),
    hourlyForecast: document.getElementById('hourly-forecast'),
    rainStatus: document.getElementById('rain-status')
};

// Weather condition icons for monochrome display
const weatherIcons = {
    'sunny': '☀',
    'partly-cloudy': '⛅',
    'cloudy': '☁',
    'rain': '🌧',
    'heavy-rain': '⛈',
    'snow': '❄',
    'fog': '🌫',
    'default': '☀'
};

// Format date
function formatDate(date) {
    const options = { weekday: 'long', month: 'long', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

// Create detailed precipitation forecast for the next hour
function createHourlyForecast(rainData) {
    elements.hourlyForecast.innerHTML = '';
    
    // Generate 60 data points for minute-by-minute precipitation
    const minuteData = [];
    
    // Create a more realistic precipitation pattern based on the base rain intensity
    const baseIntensity = rainData[0] || 0.5;
    let lastValue = baseIntensity;
    
    // Generate 60 minute data points (one per minute for the next hour)
    for (let i = 0; i < 60; i++) {
        // Create slight variations for realistic precipitation patterns
        let variation = (Math.random() - 0.5) * 0.1;
        // Ensure some correlation with the previous value
        lastValue = Math.max(0, Math.min(1, lastValue + variation));
        minuteData.push(lastValue);
    }
    
    // Find the rain stopping time (where values get below 0.1)
    let rainStopsAt = 60;
    for (let i = 10; i < minuteData.length; i++) {
        if (minuteData[i] < 0.1 && minuteData[i+1] < 0.1 && minuteData[i+2] < 0.1) {
            rainStopsAt = i;
            break;
        }
    }
    
    // Update the rain status text
    if (rainStopsAt < 60) {
        elements.rainStatus.textContent = `Rain stopping in ${rainStopsAt} min`;
    } else {
        elements.rainStatus.textContent = "Rain continuing beyond 1 hour";
    }
    
    // Create minute-by-minute bars (we'll show all 60 minutes)
    minuteData.forEach((intensity, i) => {
        const hourItem = document.createElement('div');
        hourItem.className = 'hour-item';
        
        const rainBar = document.createElement('div');
        rainBar.className = 'rain-bar';
        // Scale intensity to make it visually appealing
        rainBar.style.height = `${Math.max(1, intensity * 60)}px`;
        
        hourItem.appendChild(rainBar);
        elements.hourlyForecast.appendChild(hourItem);
    });
}

// Convert temperature between units
function convertTemperature(temp, to = 'F') {
    if (to.toUpperCase() === 'F') {
        // Convert from Celsius to Fahrenheit
        return Math.round((temp * 9/5) + 32);
    } else {
        // Convert from Fahrenheit to Celsius
        return Math.round((temp - 32) * 5/9);
    }
}

// Main function to fetch and update weather data
async function fetchWeatherData() {
    try {
        // Fetch data from our weather server API
        const response = await fetch(API_URL);
        const data = await response.json();
        
        // For demonstration purposes, let's use some placeholder data
        // as we don't know the exact format of your weather server API
        updateUI({
            temperature: data.temperature || 12,
            rainProbability: data.rain_probability || 0.85,
            // Add other properties here based on your API response
        });
    } catch (error) {
        console.error('Error fetching weather data:', error);
        // Use mock data for demonstration/testing
        updateUIWithMockData();
    }
}

// Update UI with data
function updateUI(data) {
    // Convert to Fahrenheit for display
    const tempF = convertTemperature(data.temperature);
    const feelsLikeF = convertTemperature(data.temperature - 2);
    
    // Update current conditions
    elements.temp.textContent = `${tempF}°F`;
    elements.feelsLike.textContent = `Feels Like ${feelsLikeF}°`;
    
    // Update location and date
    elements.city.textContent = 'Los Angeles, California';
    elements.date.textContent = formatDate(new Date());
    
    // Set weather icon - using a sunny icon for demonstration
    elements.weatherIcon.innerHTML = '☀';  // Simpler monochrome sun icon
    
    // Update details
    elements.sunrise.innerHTML = '7:05<span class="unit">AM</span>';
    elements.sunset.innerHTML = '6:59<span class="unit">PM</span>';
    elements.wind.innerHTML = '10.36<span class="unit">mph</span>';
    elements.humidity.innerHTML = '92<span class="unit">%</span>';
    elements.visibility.innerHTML = '›10.0<span class="unit">mi</span>';
    elements.airQuality.innerHTML = '2<span class="unit">Fair</span>';
    
    // Generate rain data for the hourly forecast
    // Higher probability means more rain in the forecast
    const baseRainIntensity = data.rainProbability;
    const rainData = Array(12).fill(0).map(() => {
        return baseRainIntensity * Math.random() * 2;
    });
    
    createHourlyForecast(rainData);
}

// Use mock data for initial display/testing
function updateUIWithMockData() {
    updateUI({
        temperature: 10, // Will be converted to ~49°F
        rainProbability: 0.4  // 40% chance of rain
    });
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    // Initial setup with mock data
    updateUIWithMockData();
    
    // Then fetch real data if available
    fetchWeatherData();
    
    // For e-ink, refresh less frequently
    setInterval(fetchWeatherData, 60 * 60 * 1000); // Every hour
});