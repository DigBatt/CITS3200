
"use strict";

// S17: Display and download daily snapshots.
async function loadSnapshots() {
  const list = document.getElementById("snapshot-list");
  const refresh = document.getElementById("btn-snapshots-refresh");

  if (!list || !refresh) return;

  refresh.disabled = true;
  list.innerHTML = '<p class="empty-state">Loading snapshots...</p>';

  try {
    const response = await fetch("/api/snapshots");

    if (!response.ok) {
      throw new Error(`Could not load snapshots (${response.status}).`);
    }

    const data = await response.json();

    const available = (data.available || []).map(day => ({
      day,
      status: "Available"
    }));

    const missing = (data.missing || []).map(day => ({
      day,
      status: "No snapshot"
    }));

    const snapshots = [...available, ...missing]
      .sort((a, b) => b.day.localeCompare(a.day));

    if (!snapshots.length) {
      list.innerHTML =
        '<p class="empty-state">No daily snapshots recorded yet.</p>';
      return;
    }

    list.replaceChildren();

    for (const snapshot of snapshots) {
      const row = document.createElement("div");
      row.className = "review-list-head";

      const label = document.createElement("span");
      label.textContent = `${snapshot.day} — ${snapshot.status}`;
      row.appendChild(label);

      if (snapshot.status === "Available") {
        const download = document.createElement("a");
        download.className = "btn-xs";
        download.textContent = "Download";
        download.href =
          `/api/snapshots/${encodeURIComponent(snapshot.day)}/download`;
        row.appendChild(download);
      }

      list.appendChild(row);
    }
  } catch (error) {
    list.textContent = `Unable to load snapshots: ${error.message}`;
  } finally {
    refresh.disabled = false;
  }
}

document.getElementById("btn-snapshots-refresh")
  ?.addEventListener("click", loadSnapshots);

document.querySelector('.app-tab[data-tab="snapshots"]')
  ?.addEventListener("click", loadSnapshots);
