// API Configuration
const API_BASE_URL = 'http://localhost:8000';

// Global variables
let currentView = 'dashboard';
let refreshInterval = null;
let categoryChart = null;
let timelineChart = null;
let priorityChart = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    startAutoRefresh();
    loadDashboardData();
    loadEmails();
});

// Setup event listeners
function setupEventListeners() {
    // Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const view = item.dataset.view;
            switchView(view);
        });
    });
    
    // Sync toggle
    document.getElementById('syncToggle').addEventListener('click', toggleSync);
    
    // Email filters
    document.getElementById('categoryFilter').addEventListener('change', loadEmails);
    document.getElementById('refreshEmailsBtn').addEventListener('click', loadEmails);
    document.getElementById('clearHistoryBtn').addEventListener('click', clearHistory);
    
    // Modal controls
    document.querySelector('.close').addEventListener('click', closeModal);
    document.getElementById('cancelReply').addEventListener('click', closeModal);
    document.getElementById('sendReply').addEventListener('click', sendReply);
    
    // Close modal on outside click
    window.addEventListener('click', (e) => {
        const modal = document.getElementById('replyModal');
        if (e.target === modal) {
            closeModal();
        }
    });
}

// Start auto-refresh
function startAutoRefresh() {
    refreshInterval = setInterval(() => {
        if (currentView === 'dashboard') {
            loadDashboardData();
        } else if (currentView === 'emails') {
            loadEmails();
        }
    }, 30000); // Refresh every 30 seconds
}

// Switch between views
function switchView(view) {
    currentView = view;
    
    // Update navigation active state
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.view === view) {
            item.classList.add('active');
        }
    });
    
    // Show selected view
    document.querySelectorAll('.view').forEach(v => {
        v.classList.remove('active');
    });
    document.getElementById(`${view}View`).classList.add('active');
    
    // Load view-specific data
    if (view === 'dashboard') {
        loadDashboardData();
    } else if (view === 'emails') {
        loadEmails();
    } else if (view === 'analytics') {
        loadAnalytics();
    }
}

// Toggle email sync
async function toggleSync() {
    try {
        const response = await fetch(`${API_BASE_URL}/toggle-sync`, {
            method: 'POST'
        });
        const data = await response.json();
        
        const indicator = document.getElementById('syncIndicator');
        const statusText = document.getElementById('syncStatusText');
        
        if (data.email_sync_enabled) {
            indicator.classList.add('active');
            statusText.textContent = 'Sync: ON';
            showNotification('Email sync enabled', 'success');
        } else {
            indicator.classList.remove('active');
            statusText.textContent = 'Sync: OFF';
            showNotification('Email sync disabled', 'info');
        }
    } catch (error) {
        console.error('Error toggling sync:', error);
        showNotification('Failed to toggle sync', 'error');
    }
}

// Load dashboard data
async function loadDashboardData() {
    try {
        const [statusRes, emailsRes] = await Promise.all([
            fetch(`${API_BASE_URL}/status`),
            fetch(`${API_BASE_URL}/emails?limit=100`)
        ]);
        
        const status = await statusRes.json();
        const emails = await emailsRes.json();
        
        // Update stats
        document.getElementById('totalEmails').textContent = status.processed_count;
        document.getElementById('queueSize').textContent = status.queue_size;
        
        // Calculate replies sent
        const repliesSent = emails.emails.filter(e => e.reply_sent).length;
        document.getElementById('totalReplies').textContent = repliesSent;
        
        // Calculate high priority emails
        const highPriority = emails.emails.filter(e => e.priority === 'HIGH').length;
        document.getElementById('highPriority').textContent = highPriority;
        
        // Update category stats
        updateCategoryStats(emails.emails);
        
        // Update recent emails
        updateRecentEmails(emails.emails.slice(-5).reverse());
        
    } catch (error) {
        console.error('Error loading dashboard:', error);
        showNotification('Failed to load dashboard data', 'error');
    }
}

// Update category statistics
function updateCategoryStats(emails) {
    const categories = {};
    emails.forEach(email => {
        const category = email.category;
        categories[category] = (categories[category] || 0) + 1;
    });
    
    const categoryBars = document.getElementById('categoryBars');
    categoryBars.innerHTML = '';
    
    const total = emails.length;
    for (const [category, count] of Object.entries(categories)) {
        const percentage = (count / total) * 100;
        
        const categoryDiv = document.createElement('div');
        categoryDiv.className = 'category-item';
        categoryDiv.innerHTML = `
            <div class="category-name">${category}</div>
            <div class="category-bar">
                <div class="category-bar-fill" style="width: ${percentage}%"></div>
            </div>
            <div class="category-count">${count}</div>
        `;
        categoryBars.appendChild(categoryDiv);
    }
}

// Update recent emails in dashboard
function updateRecentEmails(emails) {
    const recentEmailsDiv = document.getElementById('recentEmails');
    
    if (emails.length === 0) {
        recentEmailsDiv.innerHTML = '<p style="text-align: center; color: #999;">No emails processed yet</p>';
        return;
    }
    
    recentEmailsDiv.innerHTML = emails.map(email => `
        <div class="email-item" onclick="viewEmailDetails('${email.message_id}')">
            <div class="email-header">
                <span class="email-category category-${email.category.replace(' ', '')}">${email.category}</span>
                <span style="font-size: 12px; color: #999;">${new Date(email.processed_at).toLocaleDateString()}</span>
            </div>
            <div class="email-subject">${escapeHtml(email.subject)}</div>
            <div class="email-sender">${escapeHtml(email.sender)}</div>
            <div class="email-summary">${escapeHtml(email.summary.substring(0, 100))}...</div>
        </div>
    `).join('');
}

// Load emails for email management view
async function loadEmails() {
    try {
        const category = document.getElementById('categoryFilter').value;
        let url = `${API_BASE_URL}/emails?limit=100`;
        if (category) {
            url += `&category=${encodeURIComponent(category)}`;
        }
        
        const response = await fetch(url);
        const data = await response.json();
        
        displayEmails(data.emails);
        
    } catch (error) {
        console.error('Error loading emails:', error);
        showNotification('Failed to load emails', 'error');
    }
}

// Display emails in grid
function displayEmails(emails) {
    const emailGrid = document.getElementById('emailGrid');
    
    if (emails.length === 0) {
        emailGrid.innerHTML = '<div style="text-align: center; padding: 50px; color: #999;">No emails found</div>';
        return;
    }
    
    emailGrid.innerHTML = emails.map(email => `
        <div class="email-card">
            <div class="email-card-header">
                <div class="email-badges">
                    <span class="priority-badge priority-${email.priority}">${email.priority}</span>
                    <span class="email-category category-${email.category.replace(' ', '')}">${email.category}</span>
                    ${email.reply_sent ? '<span class="reply-badge"><i class="fas fa-check"></i> Reply Sent</span>' : ''}
                </div>
                <span style="font-size: 12px; color: #999;">${new Date(email.processed_at).toLocaleString()}</span>
            </div>
            <div class="email-content">
                <h4>${escapeHtml(email.subject)}</h4>
                <p style="color: #777; margin: 5px 0;">From: ${escapeHtml(email.sender)}</p>
                <div class="email-summary-text">${escapeHtml(email.summary)}</div>
            </div>
            ${email.attachments && email.attachments.length > 0 ? `
                <div class="email-attachments">
                    ${email.attachments.map(att => `
                        <span class="attachment-item"><i class="fas fa-paperclip"></i> ${escapeHtml(att.name)}</span>
                    `).join('')}
                </div>
            ` : ''}
            <div class="email-actions">
                <button class="btn-primary" onclick="openReplyModal('${escapeHtml(email.sender)}', '${escapeHtml(email.subject)}')">
                    <i class="fas fa-reply"></i> Reply
                </button>
            </div>
        </div>
    `).join('');
}

// Load analytics data
async function loadAnalytics() {
    try {
        const response = await fetch(`${API_BASE_URL}/emails?limit=500`);
        const data = await response.json();
        const emails = data.emails;
        
        // Create charts
        createCategoryChart(emails);
        createPriorityChart(emails);
        createTimelineChart(emails);
        
        // Update metrics
        updateMetrics(emails);
        
    } catch (error) {
        console.error('Error loading analytics:', error);
        showNotification('Failed to load analytics', 'error');
    }
}

// Create category distribution chart
function createCategoryChart(emails) {
    const categories = {};
    emails.forEach(email => {
        categories[email.category] = (categories[email.category] || 0) + 1;
    });
    
    const ctx = document.getElementById('categoryChart').getContext('2d');
    
    if (categoryChart) {
        categoryChart.destroy();
    }
    
    categoryChart = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: Object.keys(categories),
            datasets: [{
                data: Object.values(categories),
                backgroundColor: [
                    '#3498db', '#e74c3c', '#27ae60', '#f39c12',
                    '#9b59b6', '#1abc9c', '#95a5a6'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom'
                }
            }
        }
    });
}

// Create priority distribution chart
function createPriorityChart(emails) {
    const priorities = { HIGH: 0, MEDIUM: 0, LOW: 0 };
    emails.forEach(email => {
        priorities[email.priority]++;
    });
    
    const ctx = document.getElementById('priorityChart').getContext('2d');
    
    if (priorityChart) {
        priorityChart.destroy();
    }
    
    priorityChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['High', 'Medium', 'Low'],
            datasets: [{
                label: 'Number of Emails',
                data: [priorities.HIGH, priorities.MEDIUM, priorities.LOW],
                backgroundColor: ['#e74c3c', '#f39c12', '#27ae60']
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
}

// Create timeline chart
function createTimelineChart(emails) {
    // Group emails by date
    const emailsByDate = {};
    emails.forEach(email => {
        const date = new Date(email.processed_at).toLocaleDateString();
        emailsByDate[date] = (emailsByDate[date] || 0) + 1;
    });
    
    const dates = Object.keys(emailsByDate).slice(-7);
    const counts = dates.map(date => emailsByDate[date]);
    
    const ctx = document.getElementById('timelineChart').getContext('2d');
    
    if (timelineChart) {
        timelineChart.destroy();
    }
    
    timelineChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                label: 'Emails Processed',
                data: counts,
                borderColor: '#667eea',
                backgroundColor: 'rgba(102, 126, 234, 0.1)',
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'top'
                }
            }
        }
    });
}

// Update performance metrics
function updateMetrics(emails) {
    const total = emails.length;
    const replied = emails.filter(e => e.reply_sent).length;
    const highPriority = emails.filter(e => e.priority === 'HIGH').length;
    
    const avgResponseTime = calculateAverageResponseTime(emails);
    
    const metricsList = document.getElementById('metricsList');
    metricsList.innerHTML = `
        <div class="metric-item">
            <span class="metric-label">Total Emails Processed</span>
            <span class="metric-value">${total}</span>
        </div>
        <div class="metric-item">
            <span class="metric-label">Auto-Reply Rate</span>
            <span class="metric-value">${total ? ((replied / total) * 100).toFixed(1) : 0}%</span>
        </div>
        <div class="metric-item">
            <span class="metric-label">High Priority Rate</span>
            <span class="metric-value">${total ? ((highPriority / total) * 100).toFixed(1) : 0}%</span>
        </div>
        <div class="metric-item">
            <span class="metric-label">Avg Response Time</span>
            <span class="metric-value">${avgResponseTime} min</span>
        </div>
    `;
}

// Calculate average response time
function calculateAverageResponseTime(emails) {
    // This is a placeholder - implement based on your actual data structure
    return Math.floor(Math.random() * 30) + 5;
}

// Open reply modal
function openReplyModal(to, subject) {
    document.getElementById('replyTo').value = to;
    document.getElementById('replySubject').value = subject;
    document.getElementById('replyMessage').value = '';
    document.getElementById('replyModal').style.display = 'block';
}

// Close modal
function closeModal() {
    document.getElementById('replyModal').style.display = 'none';
}

// Send reply
async function sendReply() {
    const to = document.getElementById('replyTo').value;
    const subject = document.getElementById('replySubject').value;
    const body = document.getElementById('replyMessage').value;
    
    if (!body.trim()) {
        showNotification('Please enter a reply message', 'warning');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/reply`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email: to, subject: subject, body: body })
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            showNotification('Reply sent successfully!', 'success');
            closeModal();
            loadEmails(); // Refresh email list
        } else {
            showNotification('Failed to send reply', 'error');
        }
    } catch (error) {
        console.error('Error sending reply:', error);
        showNotification('Failed to send reply', 'error');
    }
}

// Clear email history
async function clearHistory() {
    if (confirm('Are you sure you want to clear all email history? This action cannot be undone.')) {
        try {
            const response = await fetch(`${API_BASE_URL}/clear-history`, {
                method: 'POST'
            });
            
            if (response.ok) {
                showNotification('History cleared successfully', 'success');
                loadDashboardData();
                loadEmails();
            } else {
                showNotification('Failed to clear history', 'error');
            }
        } catch (error) {
            console.error('Error clearing history:', error);
            showNotification('Failed to clear history', 'error');
        }
    }
}

// Show notification
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'}"></i>
        <span>${message}</span>
    `;
    
    // Style the notification
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        background: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 10000;
        display: flex;
        align-items: center;
        gap: 10px;
        animation: slideIn 0.3s ease;
        border-left: 4px solid ${type === 'success' ? '#27ae60' : type === 'error' ? '#e74c3c' : '#3498db'};
    `;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// View email details (placeholder for future enhancement)
function viewEmailDetails(messageId) {
    // This can be expanded to show detailed email view
    showNotification('Email details feature coming soon!', 'info');
}

// Add animation keyframes
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);