// Weather E-Ink Display Script

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
    windSpeed: document.getElementById('wind-speed'),
    windDirection: document.getElementById('wind-direction'),
    humidity: document.getElementById('humidity'),
    rainChart: document.getElementById('rain-chart'),
    rainLabels: document.getElementById('rain-labels'),
    windChart: document.getElementById('wind-chart'),
    windDirectionLabels: document.getElementById('wind-direction-labels'),
    windLabels: document.getElementById('wind-labels'),
    sunriseTime: document.getElementById('sunrise-time'),
    sunsetTime: document.getElementById('sunset-time'),
    daylightProgress: document.getElementById('daylight-progress')
};

// Time slots for charts
const timeSlots = ['Now', '3H', '6H', '9H', '12H', '15H', '18H', '21H', '24H'];

// Weather condition icons
const weatherIcons = {
    'clear': '☀️',
    'partly-cloudy': '⛅',
    'cloudy': '☁️',
    'rain': '🌧️',
    'heavy-rain': '⛈️',
    'snow': '❄️',
    'fog': '🌫️',
    'default': '🌤️'
};

// Wind direction arrows
const windArrows = {
    'N': '↑',
    'NE': '↗',
    'E': '→',
    'SE': '↘',
    'S': '↓',
    'SW': '↙',
    'W': '←',
    'NW': '↖'
};

// Format date
function formatDate(date) {
    const options = { weekday: 'long', month: 'long', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

// Create rain intensity chart
function createRainChart(rainData) {
    elements.rainChart.innerHTML = '';
    elements.rainLabels.innerHTML = '';
    
    // Create bars
    rainData.forEach((intensity, index) => {
        const bar = document.createElement('div');
        bar.className = 'bar';
        bar.style.height = `${Math.max(1, intensity * 60)}px`; // Scale to fit the chart height
        bar.style.flex = 1;
        elements.rainChart.appendChild(bar);
        
        // Create time labels (only for certain indices)
        if (index % 3 === 0 || index === rainData.length - 1) {
            const label = document.createElement('div');
            label.textContent = timeSlots[Math.floor(index / 3)];
            label.style.flex = '3';
            label.style.textAlign = 'center';
            elements.rainLabels.appendChild(label);
        }
    });
}

// Create wind speed chart
function createWindChart(windData, directions) {
    elements.windChart.innerHTML = '';
    elements.windLabels.innerHTML = '';
    elements.windDirectionLabels.innerHTML = '';
    
    // Create line chart
    let chartHtml = '<svg width="100%" height="100%" viewBox="0 0 760 60" preserveAspectRatio="none">';
    chartHtml += '<polyline points="';
    
    windData.forEach((speed, index) => {
        const x = index * (760 / (windData.length - 1));
        const y = 60 - (speed * 60 / 50); // Scale to fit the chart height
        chartHtml += `${x},${y} `;
        
        // Create direction labels
        if (index % 3 === 0 || index === windData.length - 1) {
            const dirLabel = document.createElement('div');
            dirLabel.textContent = directions[Math.floor(index / 3)] || '';
            dirLabel.style.flex = '3';
            dirLabel.style.textAlign = 'center';
            elements.windDirectionLabels.appendChild(dirLabel);
            
            // Create time labels
            const timeLabel = document.createElement('div');
            timeLabel.textContent = timeSlots[Math.floor(index / 3)];
            timeLabel.style.flex = '3';
            timeLabel.style.textAlign = 'center';
            elements.windLabels.appendChild(timeLabel);
        }
    });
    
    chartHtml += '" fill="none" stroke="black" stroke-width="1" />';
    chartHtml += '</svg>';
    elements.windChart.innerHTML = chartHtml;
}

// Update daylight progress
function updateDaylightProgress(sunriseTime, sunsetTime) {
    const now = new Date();
    const sunrise = new Date();
    const sunset = new Date();
    
    const [sunriseHours, sunriseMinutes] = sunriseTime.split(':').map(Number);
    const [sunsetHours, sunsetMinutes] = sunsetTime.split(':').map(Number);
    
    sunrise.setHours(sunriseHours, sunriseMinutes, 0);
    sunset.setHours(sunsetHours, sunsetMinutes, 0);
    
    const totalDaylight = sunset - sunrise;
    const timeElapsed = now - sunrise;
    
    let progress = 0;
    if (now > sunrise && now < sunset) {
        progress = (timeElapsed / totalDaylight) * 100;
    } else if (now > sunset) {
        progress = 100;
    }
    
    elements.daylightProgress.style.setProperty('--progress', `${progress}%`);
    
    // Update the sunrise and sunset times in the daylight bar
    elements.sunriseTime.textContent = sunriseTime;
    elements.sunsetTime.textContent = sunsetTime;
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
    // Update current conditions
    elements.temp.textContent = `${data.temperature}°C`;
    elements.feelsLike.textContent = `Feels like ${Math.round(data.temperature - 2)}°C`;
    elements.humidity.textContent = `${Math.round(data.rainProbability * 100)}%`;
    
    // For demo, use mock data for the other elements
    elements.city.textContent = 'AMSTERDAM';
    elements.date.textContent = formatDate(new Date());
    elements.weatherIcon.textContent = weatherIcons['rain']; // Based on the image showing rain
    elements.sunrise.textContent = '06:15';
    elements.sunset.textContent = '85%'; // This seems incorrect in the image, should be a time
    elements.windSpeed.textContent = '18 km/h';
    elements.windDirection.textContent = 'NW';
    
    // Create rain chart with mock data
    const rainData = [0.8, 0.7, 0.9, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.7, 0.8, 0.9, 0.7, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05];
    createRainChart(rainData);
    
    // Create wind chart with mock data
    const windData = [10, 15, 20, 18, 15, 17, 16, 15, 18];
    const windDirections = ['SW', 'W', 'NW'];
    createWindChart(windData, windDirections);
    
    // Update daylight progress
    updateDaylightProgress('06:15', '20:30');
}

// Use mock data for initial display/testing
function updateUIWithMockData() {
    updateUI({
        temperature: 12,
        rainProbability: 0.85
    });
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    // Initial setup with mock data
    updateUIWithMockData();
    
    // Then fetch real data if available
    fetchWeatherData();
    
    // Refresh data every 10 minutes (not recommended for e-ink displays that refresh slowly)
    // For e-ink, you might want to refresh less frequently, like every hour
    setInterval(fetchWeatherData, 60 * 60 * 1000); // Every hour
});