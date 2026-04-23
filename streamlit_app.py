import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta


# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Gestion Facturation & Recouvrement", layout="wide", page_icon="🇬🇳")
st.title("📊 Système de Gestion de Recouvrement GNF (V8 CRM)")

# --- BASE DE DONNÉES ET MISE À JOUR AUTOMATIQUE ---
conn = sqlite3.connect('recouvrement_v2.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT UNIQUE)''')
c.execute('''CREATE TABLE IF NOT EXISTS factures (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, numero TEXT, date_facture TEXT, montant REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS paiements (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, montant REAL, date_paiement TEXT, mode_paiement TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS relances (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, niveau TEXT, date_action TEXT, date_prochaine TEXT, mode TEXT)''')

# 🛠️ SCRIPT DE MIGRATION : Ajout des colonnes factures manquantes
c.execute("PRAGMA table_info(factures)")
cols_f = [col[1] for col in c.fetchall()]
if 'date_echeance' not in cols_f:
    c.execute("ALTER TABLE factures ADD COLUMN date_echeance TEXT")
    c.execute("UPDATE factures SET date_echeance = date(date_facture, '+30 days')")

# 🛠️ SCRIPT DE MIGRATION : Ajout des infos CRM pour les clients
c.execute("PRAGMA table_info(clients)")
cols_c = [col[1] for col in c.fetchall()]
if 'prenom' not in cols_c: c.execute("ALTER TABLE clients ADD COLUMN prenom TEXT DEFAULT ''")
if 'adresse' not in cols_c: c.execute("ALTER TABLE clients ADD COLUMN adresse TEXT DEFAULT ''")
if 'telephone' not in cols_c: c.execute("ALTER TABLE clients ADD COLUMN telephone TEXT DEFAULT ''")

conn.commit()
# --------------------------------------------------

# --- FONCTIONS UTILITAIRES ---
def get_clients(): return pd.read_sql_query("SELECT * FROM clients", conn)
def get_factures(): return pd.read_sql_query("SELECT * FROM factures", conn)
def get_paiements(): return pd.read_sql_query("SELECT * FROM paiements", conn)

def format_gnf(montant): 
    try: return f"{int(float(montant)):,} GNF".replace(",", " ")
    except: return "0 GNF"

def calculer_solde(client_id):
    try:
        cid = int(client_id) 
        c.execute("SELECT SUM(montant) FROM factures WHERE client_id=?", (cid,))
        tf = float(c.fetchone()[0] or 0.0)
        c.execute("SELECT SUM(montant) FROM paiements WHERE client_id=?", (cid,))
        tp = float(c.fetchone()[0] or 0.0)
        return tf - tp
    except: return 0.0

# --- ANALYSE FINANCIÈRE ---
def analyser_finance():
    factures = get_factures()
    paiements = get_paiements()
    clients = get_clients()
    
    if factures.empty: return pd.DataFrame(), 0, 0, 0
    
    factures['client_id'] = pd.to_numeric(factures['client_id'], errors='coerce').fillna(0).astype(int)
    factures['montant'] = pd.to_numeric(factures['montant'], errors='coerce').fillna(0.0)
    factures['date_facture'] = pd.to_datetime(factures['date_facture'])
    factures['date_echeance'] = pd.to_datetime(factures['date_echeance']).fillna(factures['date_facture'] + pd.Timedelta(days=30))
    
    if not paiements.empty:
        paiements['client_id'] = pd.to_numeric(paiements['client_id'], errors='coerce').fillna(0).astype(int)
        paiements['montant'] = pd.to_numeric(paiements['montant'], errors='coerce').fillna(0.0)
    
    paiements_par_client = paiements.groupby('client_id')['montant'].sum().to_dict() if not paiements.empty else {}
    client_dict = dict(zip(clients['id'], clients['nom']))
    
    aging_data = []
    encours_total = 0
    echus_total = 0
    
    for client_id, group in factures.sort_values('date_facture').groupby('client_id'):
        reste_a_allouer = float(paiements_par_client.get(client_id, 0.0))
        for _, row in group.iterrows():
            montant_fac = float(row['montant'])
            if reste_a_allouer >= montant_fac:
                reste_a_allouer -= montant_fac
                reste_a_payer = 0
            else:
                reste_a_payer = montant_fac - reste_a_allouer
                reste_a_allouer = 0
                
            if reste_a_payer > 0.01:
                encours_total += reste_a_payer
                jours_retard = (datetime.today() - row['date_echeance']).days 
                
                if jours_retard <= 0: tranche = "0. Non échu"
                elif jours_retard <= 30: tranche = "1. 1-30 jours"
                elif jours_retard <= 60: tranche = "2. 31-60 jours"
                elif jours_retard <= 90: tranche = "3. 61-90 jours"
                else: tranche = "4. + de 90 jours"
                
                if jours_retard > 0: echus_total += reste_a_payer
                
                aging_data.append({
                    'Client': client_dict.get(client_id, "Inconnu"), 
                    'Facture': row['numero'], 
                    'Reste à Payer': reste_a_payer, 
                    'Jours Retard': jours_retard, 
                    'Tranche': tranche
                })
                
    return pd.DataFrame(aging_data), encours_total, echus_total, factures['montant'].sum()

# --- GÉNÉRATION PDF ---
def generer_pdf_releve(client_nom, factures_df, paiements_df, solde):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="RELEVE DE COMPTE", ln=True, align='C')
    pdf.set_font("Arial", '', 12)
    pdf.cell(200, 10, txt=f"Client : {client_nom}", ln=True, align='C')
    pdf.cell(200, 10, txt=f"Date : {datetime.today().strftime('%d/%m/%Y')}", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    if solde > 0: pdf.set_text_color(255, 0, 0)
    elif solde < 0: pdf.set_text_color(0, 0, 255) # Bleu pour l'avoir
    else: pdf.set_text_color(0, 128, 0)
    texte_solde = f"SOLDE A PAYER : {format_gnf(solde)}" if solde >= 0 else f"AVOIR (CREDIT) : {format_gnf(abs(solde))}"
    pdf.cell(200, 10, txt=texte_solde, ln=True, align='C')
    pdf.set_text_color(0,0,0); pdf.ln(10); pdf.set_font("Arial", 'B', 12); pdf.cell(200, 10, txt="DETAIL :", ln=True)
    pdf.set_font("Arial", '', 10)
    if not factures_df.empty:
        for _, r in factures_df.iterrows(): 
            ech = r['Échéance'] if 'Échéance' in r else r['Date']
            pdf.cell(200, 8, txt=f"Le {r['Date']} (Echeance: {ech}) | Fac {r['N° Facture']} | {format_gnf(r['Montant (GNF)'])}", ln=True)
    if not paiements_df.empty:
        for _, r in paiements_df.iterrows(): 
            pdf.cell(200, 8, txt=f"Le {r['Date']} | Paiement {r['Mode de Paiement']} | -{format_gnf(r['Montant (GNF)'])}", ln=True)
    return pdf.output(dest='S').encode('latin-1')

def generer_pdf_relance(client_nom, solde, niveau):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 14)
    titres = {"Rappel avant échéance": "RAPPEL AVANT ECHEANCE", "Relance simple": "RELANCE SIMPLE", "Rappel suite à une première relance": "DEUXIEME RELANCE", "Mise en demeure de payer": "MISE EN DEMEURE"}
    pdf.cell(200, 10, txt=titres.get(niveau, "RELANCE"), ln=True, align='C'); pdf.ln(10); pdf.set_font("Arial", '', 12)
    pdf.cell(200, 10, txt=f"Client : {client_nom}", ln=True); pdf.cell(200, 10, txt=f"Solde impaye : {format_gnf(solde)}", ln=True)
    pdf.ln(10); pdf.multi_cell(0, 10, txt="Merci de regulariser votre situation dans les plus brefs delais.")
    return pdf.output(dest='S').encode('latin-1')

# --- NAVIGATION ---
st.sidebar.title("Navigation")
menu_principal = ["📊 Tableau de Bord Direction", "📇 Fiche Client & Historique", "🔍 Recherche Globale", "🧾 Nouvelle Facture", "💳 Saisir un Paiement", "⚠️ Module de Relances", "🎁 Avoirs & Trop-perçus"]
choix = st.sidebar.radio("Aller à", menu_principal)

# --- SECTION 1 : TABLEAU DE BORD ---
if choix == "📊 Tableau de Bord Direction":
    st.header("📈 Indicateurs de Performance")
    df_aging, encours, echus, total_facture = analyser_finance()
    total_encaisse = get_paiements()['montant'].sum() if not get_paiements().empty else 0
    
    if not df_aging.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Encours Total", format_gnf(encours))
        col2.metric("Impayés (Échus)", format_gnf(echus), delta=f"{(echus/encours*100):.1f}%")
        col3.metric("DSO (Délai moyen)", f"{int(encours/total_facture*365) if total_facture>0 else 0} jours")
        col4.metric("Efficacité Collecte", f"{(total_encaisse/(total_encaisse+encours)*100):.1f}%" if (total_encaisse+encours)>0 else "0%")
        
        st.subheader("⏱️ Balance Âgée (Basée sur l'échéance)")
        st.bar_chart(df_aging.groupby('Tranche')['Reste à Payer'].sum())
        
        st.subheader("🚨 Profils de Risque")
        risk = df_aging.groupby('Client').agg(Dette=('Reste à Payer', 'sum'), Retard_Max=('Jours Retard', 'max')).reset_index()
        risk['Risque'] = risk['Retard_Max'].apply(lambda x: "🔴 Élevé" if x > 60 else ("🟠 Moyen" if x > 30 else "🟢 Faible"))
        st.dataframe(risk, use_container_width=True, hide_index=True)
    else: st.info("Aucune donnée à analyser.")

# --- SECTION 2 : FICHE CLIENT ---
elif choix == "📇 Fiche Client & Historique":
    st.header("📇 Fiche Détaillée du Client")
    clients = get_clients()
    if not clients.empty:
        nom_c = st.selectbox("Sélectionner un client", clients['nom'])
        client_info = clients[clients['nom'] == nom_c].iloc[0]
        cid = int(client_info['id'])
        solde = calculer_solde(cid)
        
        # Affichage CRM
        st.markdown("### 👤 Informations de Contact")
        col_info1, col_info2 = st.columns(2)
        with col_info1:
            st.write(f"**Nom:** {client_info['nom']}")
            st.write(f"**Prénom:** {client_info['prenom']}")
        with col_info2:
            st.write(f"**Téléphone:** {client_info['telephone']}")
            st.write(f"**Adresse:** {client_info['adresse']}")
            
        st.divider()
        
        # Affichage dynamique des couleurs (Rouge = Dette, Bleu = Avoir, Vert = À jour)
        if solde > 0.01:
            couleur = "#ff4b4b" # Rouge
            texte_solde = f"SOLDE DÉBITEUR (À PAYER) : {format_gnf(solde)}"
        elif solde < -0.01:
            couleur = "#0066cc" # Bleu
            texte_solde = f"TROP-PERÇU (AVOIR) : {format_gnf(abs(solde))}"
        else:
            couleur = "#28a745" # Vert
            texte_solde = "SOLDE À JOUR : 0 GNF"
            
        st.markdown(f"<div style='text-align: center; background-color: {couleur}15; padding: 20px; border: 3px solid {couleur}; border-radius: 10px; margin-bottom: 20px;'><h1 style='color: {couleur}; margin: 0;'>{texte_solde}</h1></div>", unsafe_allow_html=True)
        
        c1, c2 = st.tabs(["🧾 Factures", "💳 Paiements"])
        facs = pd.read_sql_query(f"SELECT numero as 'N° Facture', date_facture as Date, date_echeance as Échéance, montant as 'Montant (GNF)' FROM factures WHERE client_id={cid}", conn)
        paies = pd.read_sql_query(f"SELECT date_paiement as Date, montant as 'Montant (GNF)', mode_paiement as 'Mode de Paiement' FROM paiements WHERE client_id={cid}", conn)
        
        with c1: st.dataframe(facs.style.format({"Montant (GNF)": "{:,.0f}"}), use_container_width=True)
        with c2: st.dataframe(paies.style.format({"Montant (GNF)": "{:,.0f}"}), use_container_width=True)
        
        pdf = generer_pdf_releve(nom_c, facs, paies, solde)
        st.download_button("📥 Télécharger Relevé PDF", pdf, f"Releve_{nom_c}.pdf", "application/pdf")
    else: st.warning("Aucun client dans la base.")

# --- SECTION 3 : RECHERCHE GLOBALE (NOUVEAU) ---
elif choix == "🔍 Recherche Globale":
    st.header("🔍 Moteur de Recherche")
    st.write("Trouvez rapidement une information en cherchant par nom, prénom, numéro de facture ou date (format AAAA-MM-JJ).")
    
    query = st.text_input("Saisissez votre recherche :", "")
    
    if query:
        q = f"%{query}%"
        
        # Recherche dans les factures
        req_fac = """
        SELECT c.nom AS Nom, c.prenom AS Prénom, f.numero AS 'N° Facture', f.date_facture AS Date, f.montant AS 'Montant (GNF)' 
        FROM factures f JOIN clients c ON f.client_id = c.id 
        WHERE c.nom LIKE ? OR c.prenom LIKE ? OR f.numero LIKE ? OR f.date_facture LIKE ?
        """
        res_fac = pd.read_sql_query(req_fac, conn, params=(q, q, q, q))
        
        # Recherche dans les paiements
        req_paie = """
        SELECT c.nom AS Nom, c.prenom AS Prénom, p.date_paiement AS Date, p.mode_paiement AS 'Mode', p.montant AS 'Montant (GNF)' 
        FROM paiements p JOIN clients c ON p.client_id = c.id 
        WHERE c.nom LIKE ? OR c.prenom LIKE ? OR p.date_paiement LIKE ? OR p.mode_paiement LIKE ?
        """
        res_paie = pd.read_sql_query(req_paie, conn, params=(q, q, q, q))
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🧾 Factures trouvées")
            if not res_fac.empty: st.dataframe(res_fac.style.format({"Montant (GNF)": "{:,.0f}"}), use_container_width=True, hide_index=True)
            else: st.info("Aucune facture correspondante.")
            
        with col2:
            st.subheader("💳 Paiements trouvés")
            if not res_paie.empty: st.dataframe(res_paie.style.format({"Montant (GNF)": "{:,.0f}"}), use_container_width=True, hide_index=True)
            else: st.info("Aucun paiement correspondant.")

# --- SECTION 4 : NOUVELLE FACTURE ---
elif choix == "🧾 Nouvelle Facture":
    st.header("🧾 Créer une Facture")
    cls = get_clients()
    opts = ["-- Nouveau Client --"] + cls['nom'].tolist()
    selection = st.selectbox("Client", opts)
    
    if selection != "-- Nouveau Client --":
        solde_c = calculer_solde(int(cls[cls['nom'] == selection]['id'].values[0]))
        if solde_c < -0.01: st.info(f"🔵 INFO : Ce client dispose d'un avoir (crédit) de {format_gnf(abs(solde_c))} à déduire de cette facture.")

    with st.form("fac_form", clear_on_submit=True):
        st.write("### Détails du Client")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            nom_nouveau = st.text_input("Nom (Obligatoire si nouveau)")
            prenom_nouveau = st.text_input("Prénom")
        with col_c2:
            tel_nouveau = st.text_input("Téléphone")
            adr_nouveau = st.text_input("Adresse")
            
        st.write("### Détails de la Facture")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            num = st.text_input("N° Facture")
            mt = st.number_input("Montant GNF", min_value=0, step=1000)
        with col_f2:
            dt_f = st.date_input("Date de Facture", datetime.today())
            dt_e = st.date_input("Date d'échéance", datetime.today() + timedelta(days=30))
            
        if st.form_submit_button("Valider la création"):
            if selection == "-- Nouveau Client --" and nom_nouveau:
                try:
                    c.execute("INSERT INTO clients (nom, prenom, adresse, telephone) VALUES (?,?,?,?)", 
                              (nom_nouveau, prenom_nouveau, adr_nouveau, tel_nouveau))
                    target_id = c.lastrowid
                except sqlite3.IntegrityError:
                    st.error("Un client portant ce Nom existe déjà.")
                    st.stop()
            elif selection != "-- Nouveau Client --": 
                target_id = int(cls[cls['nom'] == selection]['id'].values[0])
            else:
                st.error("Le Nom est requis pour créer un client.")
                st.stop()
                
            c.execute("INSERT INTO factures (client_id, numero, date_facture, date_echeance, montant) VALUES (?,?,?,?,?)", 
                      (target_id, num, dt_f.strftime("%Y-%m-%d"), dt_e.strftime("%Y-%m-%d"), float(mt)))
            conn.commit(); st.success("Facture enregistrée avec succès !"); st.rerun()

# --- SECTION 5 : PAIEMENT ---
elif choix == "💳 Saisir un Paiement":
    st.header("💳 Encaisser un Paiement")
    cls = get_clients()
    if not cls.empty:
        with st.form("pay_form", clear_on_submit=True):
            nom_p = st.selectbox("Client", cls['nom'])
            mt_p = st.number_input("Montant GNF", min_value=0, step=1000)
            md = st.selectbox("Mode", ["Espèces", "Virement", "Orange Money", "Mobile Money", "Chèque"])
            dt_p = st.date_input("Date du paiement")
            if st.form_submit_button("Enregistrer le paiement"):
                cid_p = int(cls[cls['nom'] == nom_p]['id'].values[0])
                c.execute("INSERT INTO paiements (client_id, montant, date_paiement, mode_paiement) VALUES (?,?,?,?)", (cid_p, float(mt_p), dt_p.strftime("%Y-%m-%d"), md))
                conn.commit(); st.success("Paiement enregistré avec succès.")
    else: st.warning("Veuillez d'abord créer un client.")

# --- SECTION 6 : RELANCES ---
elif choix == "⚠️ Module de Relances":
    st.header("⚠️ Relances Clients")
    df_ag, _, _, _ = analyser_finance()
    if not df_ag.empty:
        late_clients = df_ag[df_ag['Jours Retard'] > 0]['Client'].unique()
        if len(late_clients) > 0:
            sel_rel = st.selectbox("Client à relancer", late_clients)
            niv = st.selectbox("Niveau de relance", ["Rappel avant échéance", "Relance simple", "Rappel suite à une première relance", "Mise en demeure de payer"])
            if st.button("Générer la lettre de Relance"):
                client_data = get_clients()[get_clients()['nom'] == sel_rel]
                if not client_data.empty:
                    cid_rel = int(client_data['id'].values[0])
                    pdf_r = generer_pdf_relance(sel_rel, calculer_solde(cid_rel), niv)
                    st.download_button(f"📥 Télécharger {niv} (PDF)", pdf_r, f"Relance_{sel_rel}.pdf")
        else: st.success("🎉 Excellente nouvelle : Aucun retard de paiement détecté !")
    else: st.info("Aucune facture à analyser pour les relances.")

# --- SECTION 7 : AVOIRS ---
elif choix == "🎁 Avoirs & Trop-perçus":
    st.header("🎁 Clients en Crédit (Avoirs)")
    st.write("Liste des clients ayant payé plus que le montant total de leurs factures. Ce solde bleu pourra être déduit de leurs futurs achats.")
    res = []
    for _, r in get_clients().iterrows():
        s = calculer_solde(r['id'])
        if s < -0.01: res.append({"Client": r['nom'], "Téléphone": r['telephone'], "Avoir (GNF)": abs(s)})
    
    if res: 
        df_avoir = pd.DataFrame(res)
        st.dataframe(df_avoir.style.format({"Avoir (GNF)": "{:,.0f}"}), use_container_width=True, hide_index=True)
    else: st.info("Aucun client ne dispose d'un avoir actuellement.")
