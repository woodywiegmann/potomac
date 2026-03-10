import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

plt.rcParams.update({
    'font.family': 'Segoe UI',
    'axes.spines.top': False,
    'axes.spines.right': False,
})

DARK_TEAL = '#0a5c5c'
ACCENT_TEAL = '#00bfa5'
LIGHT_BG = '#f7fafa'
BAR_COLOR = '#1a8a8a'
AVG_BAR_COLOR = '#e07020'
GRID_COLOR = '#d0dede'

# ── Data from HubSpot reports, Jan 1-21 2026 (five core reps only) ────────
REPS = ['Woody Wiegmann', 'Bradley Whittaker', 'Bally Diakite',
        'Gregory Levesque', 'Ravneet Chadha']

minutes_data = {
    'Woody Wiegmann':     680.14,
    'Bradley Whittaker':  605.77,
    'Bally Diakite':      257.21,
    'Gregory Levesque':   195.95,
    'Ravneet Chadha':      91.90,
}

logged_calls_data = {
    'Gregory Levesque':   868,
    'Bally Diakite':      772,
    'Ravneet Chadha':     767,
    'Bradley Whittaker':  634,
    'Woody Wiegmann':     551,
}

avg_duration = {
    name: minutes_data[name] / logged_calls_data[name]
    for name in REPS
}

# Sort each dataset for its own chart (descending)
min_sorted = sorted(minutes_data.items(), key=lambda x: x[1], reverse=True)
names_min  = [x[0] for x in min_sorted]
vals_min   = [x[1] for x in min_sorted]

avg_sorted = sorted(avg_duration.items(), key=lambda x: x[1], reverse=True)
names_avg  = [x[0] for x in avg_sorted]
vals_avg   = [x[1] for x in avg_sorted]

# ── Build dashboard ───────────────────────────────────────────────────────
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 9), gridspec_kw={'wspace': 0.45})
fig.patch.set_facecolor(LIGHT_BG)
fig.subplots_adjust(top=0.76, bottom=0.10)

fig.suptitle(
    'PFM Call Quality Dashboard  —  January 1–21, 2026',
    fontsize=24, fontweight='bold', color=DARK_TEAL, y=0.97,
)
fig.text(
    0.5, 0.88,
    'Source: HubSpot "Calling minute usage" (actual minutes billed) & Self-Reported Logged Calls',
    ha='center', fontsize=13, color='#5a7a7a', style='italic',
)
fig.text(
    0.5, 0.845,
    'Suggested cadence: monthly',
    ha='center', fontsize=13, color='#5a7a7a', style='italic',
)

# ── Panel 1: Total Minutes on Phone ──────────────────────────────────────
y_pos1 = np.arange(len(names_min))
bars1 = ax1.barh(y_pos1, vals_min, color=BAR_COLOR, height=0.6, edgecolor='white', linewidth=0.5)
ax1.set_yticks(y_pos1)
ax1.set_yticklabels(names_min, fontsize=13)
ax1.invert_yaxis()
ax1.set_xlabel('Minutes', fontsize=13, color=DARK_TEAL)
ax1.set_title('Total Calling Minutes', fontsize=16, fontweight='bold',
              color=DARK_TEAL, pad=14)
ax1.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))
ax1.set_facecolor(LIGHT_BG)
ax1.grid(axis='x', color=GRID_COLOR, linewidth=0.5)
ax1.set_axisbelow(True)

for bar, val in zip(bars1, vals_min):
    ax1.text(bar.get_width() + 8, bar.get_y() + bar.get_height() / 2,
             f'{val:,.1f}', va='center', fontsize=12, color=DARK_TEAL, fontweight='bold')

# ── Panel 2: Avg Call Duration (minutes / logged calls) ──────────────────
y_pos2 = np.arange(len(names_avg))
bars2 = ax2.barh(y_pos2, vals_avg, color=AVG_BAR_COLOR, height=0.6, edgecolor='white', linewidth=0.5)
ax2.set_yticks(y_pos2)
ax2.set_yticklabels(names_avg, fontsize=13)
ax2.invert_yaxis()
ax2.set_xlabel('Avg Minutes per Call', fontsize=13, color=DARK_TEAL)
ax2.set_title('Average Call Duration\n(Total Minutes ÷ Self-Reported Logged Calls)',
              fontsize=16, fontweight='bold', color=DARK_TEAL, pad=14)
ax2.set_facecolor(LIGHT_BG)
ax2.grid(axis='x', color=GRID_COLOR, linewidth=0.5)
ax2.set_axisbelow(True)

for bar, val in zip(bars2, vals_avg):
    ax2.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
             f'{val:.2f}', va='center', fontsize=12, color='#8b4513', fontweight='bold')

# ── Footer ────────────────────────────────────────────────────────────────
fig.text(0.5, 0.02,
         'Prepared for Mike Heavey by Woody Wiegmann',
         ha='center', fontsize=11, color='#5a7a7a', style='italic')

plt.savefig(
    r'c:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\ai bruh\call_quality_dashboard.png',
    dpi=180, bbox_inches='tight', facecolor=fig.get_facecolor(),
)
print('Dashboard saved to call_quality_dashboard.png')
