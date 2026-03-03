from shiny import App, reactive, render, ui
import pandas as pd
import numpy as np
import jinja2
import base64

# =============================================================================
# Constants and Logic
# =============================================================================
CONST_BASE = 1.6569
COEF_ES = -0.4006
COEF_VOL = -0.0333
COEF_AGE = 0.0168
DEFAULT_ELECTRICITY_PRICE = 0.29  # $/kWh

# Load Database
df_es = pd.read_csv("ult_freezer_database.csv")

# =============================================================================
# Helper: Savings Gauges HTML
# =============================================================================
def make_savings_gauges(df):
    if df.empty:
        return "<p style='color:#888;font-size:0.85rem;'>No units added yet.</p>"
    html = ""
    for _, row in df.iterrows():
        pred  = row["Predicted Energy Use (kWh/Year)"]
        bench = row["Energy Star Benchmark Avg (kWh/Year)"]
        cost  = row["Potential Annual Cost Savings ($/Year)"]
        pct_over = min(max((pred - bench) / bench, 0), 1.0) if bench > 0 else 0
        if pct_over == 0:
            color = "#4a9d6f"
            label = "✓ At or below benchmark"
            bar_pct = min(max(pred / bench if bench > 0 else 1, 0.05) * 100, 100)
        else:
            color = "#e05a5a"
            label = f"⚠ {pct_over*100:.0f}% above Energy Star benchmark"
            bar_pct = min(100, 40 + pct_over * 60)
        cost_color = "#4a9d6f" if cost >= 0 else "#e05a5a"
        html += f'''
        <div style="margin-bottom:12px;background:#f8f9fa;border-radius:8px;padding:10px 14px;border:1px solid #dee2e6;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                <strong style="font-size:0.85rem;">{row["ID"]}</strong>
                <span style="font-size:0.78rem;color:#666;">{label}</span>
            </div>
            <div style="background:#e9ecef;border-radius:4px;height:10px;overflow:hidden;">
                <div style="width:{bar_pct:.1f}%;background:{color};height:100%;border-radius:4px;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:0.78rem;color:#555;">
                <span>Predicted: <strong>{int(pred):,} kWh/yr</strong></span>
                <span>Benchmark: <strong>{int(bench):,} kWh/yr</strong></span>
                <span style="color:{cost_color};">Savings: <strong>${cost:,.2f}/yr</strong></span>
            </div>
        </div>'''
    return html


# =============================================================================
# Server Logic
# =============================================================================
def server(input, output, session):
    inventory    = reactive.Value(pd.DataFrame())
    unit_counter = reactive.Value(0)

    @reactive.effect
    @reactive.event(input.add_btn)
    def _add_unit():
        col_80 = "Daily Energy Consumption at -80ºC (kWh/day)"
        col_70 = "Daily Energy Consumption at -70ºC (kWh/day)"
        using_fallback = False
        if input.temp() == "-70ºC":
            target_col = col_70 if col_70 in df_es.columns else col_80
            using_fallback = target_col == col_80
        else:
            target_col = col_80

        temp_df = df_es.copy()
        temp_df['dist'] = (temp_df['Total Volume (cu. ft.)'] - input.vol()).abs()
        neighbors = temp_df.nsmallest(5, 'dist')
        avg_es_daily = neighbors[target_col].mean()
        avg_es_year  = avg_es_daily * 365
        best_model   = neighbors.loc[neighbors[target_col].idxmin()]['Model Name']

        es_adj           = COEF_ES if input.is_es() else 0
        pred_daily_kwh   = (CONST_BASE + es_adj + (COEF_VOL * input.vol()) + (COEF_AGE * input.age())) * input.vol()
        pred_efficiency  = pred_daily_kwh / input.vol() if input.vol() > 0 else 0
        pred_year_kwh    = pred_daily_kwh * 365
        baseline_yr      = (CONST_BASE + (COEF_VOL * input.vol()) + (COEF_AGE * input.age())) * 365
        annual_kwh_sav   = avg_es_year - baseline_yr
        annual_cost_sav  = annual_kwh_sav * input.elec_rate()

        new_count = unit_counter() + 1
        unit_counter.set(new_count)
        fallback_note = " (⚠ -70ºC data unavailable, used -80ºC benchmark)" if using_fallback else ""

        new_row = pd.DataFrame({
            "ID":                                              [f"Unit {new_count}"],
            "Storage Volume (cu. ft.)":                        [input.vol()],
            "Age (Years)":                                     [input.age()],
            "Temp":                                            [input.temp() + fallback_note],
            "Energy Star?":                                    ["Yes" if input.is_es() else "No"],
            "Predicted Efficiency (kWh/cu ft/day)":            [round(pred_efficiency, 3)],
            "Predicted Energy Use (kWh/day)":                  [round(pred_daily_kwh, 2)],
            "Predicted Energy Use (kWh/Year)":                 [round(pred_year_kwh, 0)],
            "Energy Star Alternative Avg (kWh/Year)":            [round(avg_es_year, 0)],
            "Potential Annual Savings (kWh/Year)":             [round(annual_kwh_sav, 0)],
            "Potential Annual Cost Savings ($/Year)":          [round(annual_cost_sav, 2)],
            "Recommended Energy Star Model (Closest Volume)":  [best_model],
        })
        inventory.set(pd.concat([inventory(), new_row], ignore_index=True))

    @reactive.effect
    @reactive.event(input.clear_btn)
    def _clear_inventory():
        inventory.set(pd.DataFrame())

    # ── KPI Cards ──────────────────────────────────────────────────────────────
    @output
    @render.ui
    def kpi_cards():
        df = inventory()
        n          = len(df)
        total_kwh  = df["Predicted Energy Use (kWh/Year)"].sum()          if not df.empty else 0
        total_cost = df["Potential Annual Cost Savings ($/Year)"].sum()   if not df.empty else 0
        total_sav  = df["Potential Annual Savings (kWh/Year)"].sum()      if not df.empty else 0

        def card(title, value, sub, color):
            return ui.div(
                ui.div(title, style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.05em;color:#888;margin-bottom:4px;"),
                ui.div(value, style=f"font-size:1.5rem;font-weight:700;color:{color};line-height:1;"),
                ui.div(sub,   style="font-size:0.75rem;color:#aaa;margin-top:2px;"),
                style="background:#fff;border:1px solid #dee2e6;border-radius:10px;padding:16px 20px;"
                      "flex:1;min-width:140px;box-shadow:0 1px 4px rgba(0,0,0,0.05);"
            )

        return ui.div(
            card("Total Units",          str(n),                    "in inventory",          "#003262"),
            card("Total Energy Use",     f"{int(total_kwh):,} kWh", "predicted / year",      "#e07b39"),
            card("Potential kWh Savings",f"{int(total_sav):,} kWh", "vs Energy Star models / year",   "#4a9d6f"),
            card("Potential Cost Savings",f"${total_cost:,.2f}",    "per year",              "#5b8fcf"),
            style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px;"
        )

    # ── Savings Gauges ─────────────────────────────────────────────────────────
    @output
    @render.ui
    def savings_gauges():
        return ui.div(
            ui.HTML(make_savings_gauges(inventory())),
            style="margin-bottom:20px;"
        )

    # ── Inventory Table ────────────────────────────────────────────────────────
    @output
    @render.table
    def inventory_table():
        df = inventory()
        if df.empty:
            return pd.DataFrame({"Status": ["No units added yet. Use the sidebar to add a freezer."]})
        return df

    # ── Freezer Selector & Detail Card ────────────────────────────────────────
    @output
    @render.ui
    def freezer_selector():
        df = inventory()
        if df.empty:
            return ui.div()
        return ui.input_select("selected_id", "Quick Detail Select:",
                               {row['ID']: row['ID'] for _, row in df.iterrows()})

    @output
    @render.ui
    def detail_card():
        df = inventory()
        if df.empty:
            return ui.div()
        sel = input.selected_id() if hasattr(input, 'selected_id') else None
        if not sel:
            return ui.div()
        row = df[df['ID'] == sel]
        if row.empty:
            return ui.div()
        row = row.iloc[0]
        return ui.div(
            ui.h5(f"Details — {sel}"),
            ui.tags.table(
                *[ui.tags.tr(
                    ui.tags.td(ui.tags.strong(col), style="padding-right:12px;"),
                    ui.tags.td(str(row[col]))
                ) for col in df.columns if col != "ID"],
                style="font-size:0.85rem;"
            ),
            style="background:#fff;border:1px solid #dee2e6;border-radius:6px;padding:12px;margin-top:10px;"
        )

    # ── CSV Export ─────────────────────────────────────────────────────────────
    @output
    @render.ui
    def export_btn_ui():
        df = inventory()
        if df.empty:
            return ui.div()
        b64  = base64.b64encode(df.to_csv(index=False).encode()).decode()
        href = f"data:text/csv;base64,{b64}"
        return ui.div(
            ui.tags.a(
                "⬇ Export Inventory to CSV",
                href=href,
                download="ult_freezer_inventory.csv",
                style="display:inline-block;padding:8px 18px;background:#003262;color:#fff;"
                      "border-radius:6px;text-decoration:none;font-size:0.85rem;font-weight:600;"
                      "margin-bottom:14px;"
            )
        )


# =============================================================================
# UI Definition
# =============================================================================
app_ui = ui.page_fluid(
    ui.tags.head(
        ui.tags.style("""
            .app-header { background:#003262; color:white; padding:20px; margin-bottom:20px; }
            .input-section { background:#f8f9fa; padding:15px; border-radius:8px; border:1px solid #dee2e6; }
            table { font-size:0.85rem; }
            .btn-danger-outline { color:#dc3545; border-color:#dc3545; background:white; }
            .btn-danger-outline:hover { background:#dc3545; color:white; }
            .section-title { font-size:0.85rem; font-weight:600; color:#555; text-transform:uppercase;
                             letter-spacing:0.05em; margin-bottom:10px;
                             border-bottom:2px solid #e9ecef; padding-bottom:4px; }
        """)
    ),

    ui.div(
        ui.h2("UC ULT Freezer Savings Calculator"),
        ui.p("Benchmarking Facility Inventory against Energy Star performance"),
        class_="app-header"
    ),

    ui.layout_sidebar(
        ui.sidebar(
            ui.div(
                ui.h4("Input Parameters"),
                ui.input_numeric("vol",  "Storage Volume (cu. ft.)", value=20.0, min=0.1, step=0.1),
                ui.input_numeric("age",  "Age of Unit (Years)",      value=5,    min=0),
                ui.input_select( "temp", "Operating Temperature",    choices=["-80ºC", "-70ºC"]),
                ui.input_switch( "is_es","Is currently Energy Star?"),
                ui.hr(),
                ui.input_numeric("elec_rate", "Electricity Rate ($/kWh)",
                                 value=DEFAULT_ELECTRICITY_PRICE, min=0.01, step=0.01),
                ui.input_action_button("add_btn",   "Add to Inventory", class_="btn-primary w-100"),
                ui.br(), ui.br(),
                ui.input_action_button("clear_btn", "Clear Inventory",  class_="btn-danger-outline w-100"),
                ui.hr(),
                ui.output_ui("freezer_selector"),
                ui.output_ui("detail_card"),
                class_="input-section"
            ),
            width=370
        ),

        ui.div(
            ui.div("Summary", class_="section-title"),
            ui.output_ui("kpi_cards"),

            ui.div("Per-Unit Savings Potential", class_="section-title"),
            ui.output_ui("savings_gauges"),

            ui.output_ui("export_btn_ui"),

            ui.div("Full Inventory Table", class_="section-title"),
            ui.output_table("inventory_table"),
            ui.hr(),
            ui.p(
                "Note: 'Potential Annual Savings' reflects how much energy could be saved by replacing "
                "the unit with a comparably-sized Energy Star model. Calculations are based on linear "
                "regression and k-Nearest Neighbors analysis of current Energy Star models.",
                style="font-size:0.8rem;color:#888;"
            )
        )
    )

app = App(app_ui, server)