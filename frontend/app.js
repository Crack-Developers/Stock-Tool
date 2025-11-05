// ✅ Simplified app.js with auto login/logout and profile display

const {
  auth,
  db,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  doc,
  setDoc,
  getDoc
} = window.firebaseModules;

const API_BASE = "http://127.0.0.1:5000";
let tickerList = [];
let fuse;
let selectedTickers = [];
let userEmail = null;

// -----------------------------
// Firebase Authentication
// -----------------------------
const loginBtn = document.getElementById("loginBtn");
const userInfo = document.getElementById("userInfo");
const userPhoto = document.getElementById("userPhoto");

loginBtn.addEventListener("click", async () => {
  try {
    if (auth.currentUser) {
      // ✅ Sign out instantly
      await signOut(auth);
      localStorage.removeItem("user");
      window.location.href = "index.html";
    } else {
      // ✅ Sign in
      const provider = new GoogleAuthProvider();
      const result = await signInWithPopup(auth, provider);
      const user = result.user;
      localStorage.setItem("user", JSON.stringify({
        name: user.displayName,
        email: user.email,
        photo: user.photoURL
      }));
      console.log("✅ Logged in:", user.displayName);
    }
  } catch (error) {
    console.error("❌ Auth error:", error);
    alert("Authentication failed. Please try again.");
  }
});

onAuthStateChanged(auth, async (user) => {
  if (user) {
    userEmail = user.email;
    loginBtn.textContent = "Sign Out";
    loginBtn.style.background = "#ef4444";
    loginBtn.style.color = "#fff";

    userInfo.textContent = `Logged in as ${user.displayName}`;
    userPhoto.src = user.photoURL;
    userPhoto.style.display = "block";

    await loadUserPreferences();
  } else {
    userEmail = null;
    loginBtn.textContent = "Login with Google";
    loginBtn.style.background = "#2563eb";
    userInfo.textContent = "";
    userPhoto.style.display = "none";
  }
});

// -----------------------------
// Load tickers list from Flask API
// -----------------------------
async function loadTickers() {
  try {
    const resp = await fetch(`${API_BASE}/api/tickers`);
    tickerList = await resp.json();
    fuse = new Fuse(tickerList, { keys: ["symbol", "name"], threshold: 0.3 });
  } catch (err) {
    console.error("Error loading tickers:", err);
    alert("Unable to load company list. Please ensure backend is running.");
  }
}

// -----------------------------
// Render company chips
// -----------------------------
function renderChips() {
  const c = document.getElementById("chips");
  c.innerHTML = "";
  selectedTickers.forEach((s) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerText = s;

    const x = document.createElement("button");
    x.innerText = "×";
    x.onclick = async () => {
      selectedTickers = selectedTickers.filter((t) => t !== s);
      renderChips();
      await saveUserPreferences();
    };

    chip.appendChild(x);
    c.appendChild(chip);
  });
}

// -----------------------------
// Find ticker by search
// -----------------------------
function findTicker(query) {
  if (!query || !fuse) return null;
  const result = fuse.search(query);
  return result.length > 0 ? result[0].item.symbol : null;
}

// -----------------------------
// Add button event
// -----------------------------
document.getElementById("addBtn").addEventListener("click", async () => {
  const query = document.getElementById("companyInput").value.trim();
  if (!query) return alert("Please enter a company name or symbol.");

  const symbol = findTicker(query);
  if (symbol && !selectedTickers.includes(symbol)) {
    selectedTickers.push(symbol);
    renderChips();
    await saveUserPreferences();
  } else {
    alert("Company not found or already added.");
  }

  document.getElementById("companyInput").value = "";
});

// -----------------------------
// Save user preferences in Firestore
// -----------------------------
async function saveUserPreferences() {
  if (!userEmail) return;
  const start = document.getElementById("startDate").value;
  const end = document.getElementById("endDate").value;

  try {
    await setDoc(doc(db, "users", userEmail), {
      tickers: selectedTickers,
      start,
      end
    });
  } catch (err) {
    console.error("Firestore save error:", err);
  }
}

// -----------------------------
// Load user preferences from Firestore
// -----------------------------
async function loadUserPreferences() {
  if (!userEmail) return;
  try {
    const ref = doc(db, "users", userEmail);
    const snap = await getDoc(ref);
    if (snap.exists()) {
      const data = snap.data();
      selectedTickers = data.tickers || [];
      document.getElementById("startDate").value = data.start || "";
      document.getElementById("endDate").value = data.end || "";
      renderChips();
      if (selectedTickers.length > 0) await fetchAndRender();
    }
  } catch (err) {
    console.error("Firestore load error:", err);
  }
}

// -----------------------------
// Fetch stock data and render charts
// -----------------------------
document.getElementById("submitBtn").addEventListener("click", async () => {
  await saveUserPreferences();
  await fetchAndRender();
});

async function fetchAndRender() {
  const start = document.getElementById("startDate").value;
  const end = document.getElementById("endDate").value;

  if (!start || !end || selectedTickers.length === 0) {
    alert("Select date range and add at least one company.");
    return;
  }

  const results = document.getElementById("results");
  results.innerHTML = "<p class='loading'>Fetching stock data...</p>";

  try {
    const resp = await fetch(`${API_BASE}/api/data`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tickers: selectedTickers, start, end })
    });

    const payload = await resp.json();
    if (payload.error) {
      results.innerHTML = `<p class='error'>⚠️ ${payload.error}</p>`;
      return;
    }

    renderCharts(payload.data);
  } catch (err) {
    console.error("Data fetch error:", err);
    results.innerHTML = "<p class='error'>⚠️ Failed to fetch stock data.</p>";
  }
}

// -----------------------------
// Render charts using Plotly
// -----------------------------
function renderCharts(dataObj) {
  const results = document.getElementById("results");
  results.innerHTML = "";

  Object.keys(dataObj).forEach((symbol) => {
    const item = dataObj[symbol];
    const wrapper = document.createElement("div");
    wrapper.className = "chart-card";
    wrapper.innerHTML = `<h3>${symbol}</h3>`;
    results.appendChild(wrapper);

    if (item.error) {
      wrapper.innerHTML += `<p class='error'>${item.error}</p>`;
      return;
    }

    const priceDiv = document.createElement("div");
    priceDiv.className = "price";
    priceDiv.innerText = `Current: ${parseFloat(item.current).toFixed(2)} USD`;
    wrapper.appendChild(priceDiv);

    const chartDiv = document.createElement("div");
    chartDiv.id = `chart-${symbol}`;
    chartDiv.className = "chart";
    wrapper.appendChild(chartDiv);

    const data = item.data.map((d) => ({ x: d.Date, y: d.Close }));

    Plotly.newPlot(
      chartDiv,
      [
        {
          x: data.map((d) => d.x),
          y: data.map((d) => d.y),
          type: "scatter",
          mode: "lines+markers",
          line: { width: 2.5 },
          marker: { size: 5 }
        }
      ],
      {
        title: `${symbol} - Price Trend`,
        xaxis: { title: "Date" },
        yaxis: { title: "Close (USD)" },
        plot_bgcolor: "#f9f9fc",
        paper_bgcolor: "#f9f9fc"
      },
      { displayModeBar: false }
    );
  });
}

// -----------------------------
// Initialize
// -----------------------------
loadTickers();
