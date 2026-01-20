from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import pyodbc
import json
import os
from datetime import datetime, timedelta
import traceback

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

CONFIG_FILE = 'config.json'

def carregar_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        return {}
    except json.JSONDecodeError:
        return {}
    except Exception as e:
        print(f"Erro ao carregar configuração: {str(e)}")
        return {}

def salvar_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Erro ao salvar configuração: {str(e)}")
        return False

def conectar_banco():
    config = carregar_config()
    if 'database' not in config:
        return None
    db_config = config['database']
    try:
        conn_str = (
            f"DRIVER={{SQL Server}};"
            f"SERVER={db_config.get('server', '')};"
            f"DATABASE={db_config.get('database', '')};"
            f"UID={db_config.get('username', '')};"
            f"PWD={db_config.get('password', '')}"
        )
        conn = pyodbc.connect(conn_str)
        return conn
    except Exception as e:
        print(f"Erro na conexão: {str(e)}")
        return None

@app.route('/')
def index():
    config = carregar_config()
    if 'database' not in config:
        return redirect(url_for('conexao'))
    return redirect(url_for('buscar_produto'))

@app.route('/conexao', methods=['GET', 'POST'])
def conexao():
    config = carregar_config()
    db_config = config.get('database', {})
    if request.method == 'POST':
        nova_config = {
            'server': request.form.get('server', ''),
            'database': request.form.get('database', ''),
            'username': request.form.get('username', ''),
            'password': request.form.get('password', '')
        }
        config['database'] = nova_config
        salvar_config(config)
        try:
            conn_str = (
                f"DRIVER={{SQL Server}};"
                f"SERVER={nova_config['server']};"
                f"DATABASE={nova_config['database']};"
                f"UID={nova_config['username']};"
                f"PWD={nova_config['password']}"
            )
            conn = pyodbc.connect(conn_str)
            conn.close()
            return redirect(url_for('buscar_produto'))
        except Exception as e:
            return render_template('conexao.html', config=nova_config, mensagem=f"Erro na conexão: {str(e)}", tipo_mensagem="error")
    return render_template('conexao.html', config=db_config)

@app.route('/buscar', methods=['GET', 'POST'])
def buscar_produto():
    conn = conectar_banco()
    if not conn:
        return redirect(url_for('conexao'))
    resultados = []
    termo_busca = ""
    if request.method == 'POST':
        termo_busca = request.form.get('termo_busca', '').strip()
        if termo_busca:
            try:
                cursor = conn.cursor()
                query = """
                SELECT DISTINCT Codigo, Descricao, Cod_EAN 
                FROM PRODU 
                WHERE CAST(Codigo AS VARCHAR(50)) LIKE ? 
                   OR Cod_EAN LIKE ? 
                   OR Descricao LIKE ? 
                ORDER BY Descricao
                """
                termo_like = f'%{termo_busca}%'
                cursor.execute(query, termo_like, termo_like, termo_like)
                colunas = [column[0] for column in cursor.description]
                resultados = [dict(zip(colunas, row)) for row in cursor.fetchall()]
                cursor.close()
            except Exception as e:
                print(f"Erro na busca: {str(e)}")
                resultados = []
    conn.close()
    return render_template('buscar_produto.html', resultados=resultados, termo_busca=termo_busca)

@app.route('/produto/<int:codigo>', methods=['GET', 'POST'])
def detalhes_produto(codigo):
    conn = conectar_banco()
    if not conn:
        return redirect(url_for('conexao'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Codigo, Descricao, Cod_EAN FROM PRODU WHERE Codigo = ?", codigo)
        produto_info = cursor.fetchone()
        if not produto_info:
            return "Produto não encontrado", 404
        produto = {'codigo': produto_info[0], 'descricao': produto_info[1], 'cod_ean': produto_info[2]}
        data_fim = datetime.now()
        data_inicio = data_fim - timedelta(days=90)
        if request.method == 'POST':
            data_inicio_form = request.form.get('data_inicio', '')
            data_fim_form = request.form.get('data_fim', '')
            if data_inicio_form:
                try: data_inicio = datetime.strptime(data_inicio_form, '%Y-%m-%d')
                except: pass
            if data_fim_form:
                try: data_fim = datetime.strptime(data_fim_form, '%Y-%m-%d')
                except: pass
        data_inicio_str = data_inicio.strftime('%Y%m%d 00:00:00')
        data_fim_str = data_fim.strftime('%Y%m%d 23:59:59')
        query_estoque = """
        SELECT pd.Codigo AS Cod_Produto, pd.Descricao AS Desc_Produto, dp.Cod_Lote, dp.Dat_Vencim,
               Qtd_Fisico = CASE WHEN IsNull(pm.FlgExbEstPrcAprPrd, 0) = 1 THEN dp.Qtd_Fisico / IsNull(ap.Fat_CnvApr, 1) ELSE dp.Qtd_Fisico END,
               Qtd_Solicitado = CASE WHEN IsNull(pm.FlgExbEstPrcAprPrd, 0) = 1 THEN dp.Qtd_Solicitado / IsNull(ap.Fat_CnvApr, 1) ELSE dp.Qtd_Solicitado END,
               dp.Cod_Dep AS Deposito, Loc_Fis = dbo.FN_FormataEndereco(dp.Num_Rua, dp.Num_Col, dp.Num_Niv, dp.Num_Apt), cl.Descricao AS Linha
        FROM PRLTL dp INNER JOIN PARAM pm ON dp.Cod_Estabe = pm.Cod_Estabe INNER JOIN PRODU pd ON dp.Cod_Produt = pd.Codigo
        LEFT JOIN TBZON zn ON (dp.Cod_Estabe = zn.Cod_Estabe AND dp.Cod_Dep = zn.Cod_Dep AND dp.Num_Rua BETWEEN zn.Num_RuaIni AND zn.Num_RuaFim)
        LEFT JOIN DPXPR d ON (dp.Cod_Estabe = d.Cod_Estabe AND dp.Cod_Dep = d.Cod_Dep AND dp.Cod_Produt = d.Cod_Produt)
        LEFT JOIN PRXAP ap ON dp.Cod_Produt = ap.Cod_Produt AND IsNull(ap.Flg_Padrao, 0) = 1
        LEFT JOIN CLASS cl ON pd.Cod_Classif = cl.Codigo
        WHERE dp.Cod_Estabe = 0 AND dp.Cod_Produt = ? AND dp.Qtd_Fisico > 0
        UNION ALL
        SELECT p.Codigo AS Cod_Produto, p.Descricao AS Desc_Produto, fr.Cod_Lote, fr.Dat_Vencim,
               Qtd_Fisico = CASE WHEN IsNull(pm.FlgExbEstPrcAprPrd, 0) = 1 THEN fr.Qtd_Fisico / IsNull(ap.Fat_CnvApr, 1) ELSE fr.Qtd_Fisico END,
               Qtd_Solicitado = CASE WHEN IsNull(pm.FlgExbEstPrcAprPrd, 0) = 1 THEN fr.Qtd_Solicitado / IsNull(ap.Fat_CnvApr, 1) ELSE fr.Qtd_Solicitado END,
               fr.Cod_Dep AS Deposito, Loc_Fis = d.Cod_LocFis, cl.Descricao AS Linha
        FROM PRLOT fr INNER JOIN PARAM pm ON fr.Cod_Estabe = pm.Cod_Estabe INNER JOIN PRODU p ON fr.Cod_Produt = p.Codigo
        INNER JOIN DPXPR d ON (fr.Cod_Estabe = d.Cod_Estabe AND fr.Cod_Dep = d.Cod_Dep AND fr.Cod_Produt = d.Cod_Produt)
        LEFT JOIN PRXAP ap ON fr.Cod_Produt = ap.Cod_Produt AND IsNull(ap.Flg_Padrao, 0) = 1
        LEFT JOIN CLASS cl ON p.Cod_Classif = cl.Codigo
        WHERE fr.Cod_Estabe = 0 AND fr.Cod_Produt = ? AND fr.Qtd_Fisico > 0
        ORDER BY Deposito, Loc_Fis, Dat_Vencim
        """
        cursor.execute(query_estoque, codigo, codigo)
        colunas_estoque = [column[0] for column in cursor.description]
        estoque = [dict(zip(colunas_estoque, row)) for row in cursor.fetchall()]
        query_entradas = """
        SELECT cb.Cod_Estabe, cb.Protocolo, cb.Numero, cb.Tip_NF, cb.Dat_Entrada, cb.Dat_Emissao, it.Dat_Movimento,
               (IsNull(it.Qtd_Pedido, 0) + IsNull(it.Qtd_Bonificacao, 0)) AS C_Quantidade, it.Qtd_Bonificacao, it.Cod_Lote,
               C_DesEmitente = CASE WHEN cb.Cod_EmiFornec > 0 THEN (SELECT Razao_Social FROM FORNE WHERE Codigo = cb.Cod_EmiFornec)
                                    WHEN cb.Cod_EmiCliente > 0 THEN (SELECT Razao_Social FROM CLIEN WHERE Codigo = cb.Cod_EmiCliente)
                                    WHEN cb.Cod_EmiTransp > 0 THEN (SELECT Razao_Social FROM TRANS WHERE Codigo = cb.Cod_EmiTransp) ELSE '' END,
               (x.Des_UnvApr + ' ' + x.Des_Apr) AS C_DesApr,
               Qtd_ComApr = CASE WHEN x.Fat_CnvApr > 0 THEN Round((IsNull(it.Qtd_Pedido, 0) + IsNull(it.Qtd_Bonificacao, 0)) * 1.0 / x.Fat_CnvApr, 2) ELSE 0 END
        FROM NFECB cb INNER JOIN NFEIT it ON (cb.Cod_Estabe = it.Cod_Estabe) AND (cb.Protocolo = it.Protocolo)
        LEFT JOIN PRXAP x ON (it.Cod_Produto = x.Cod_Produt AND x.Flg_Padrao = 1)
        WHERE cb.Cod_Estabe IN (0) AND cb.Status = 'F' AND it.Cod_Produto = ? AND it.Dat_Movimento >= ? AND it.Dat_Movimento <= ? AND cb.Tip_NF = 'C'
        ORDER BY it.Dat_Movimento DESC
        """
        cursor.execute(query_entradas, codigo, data_inicio_str, data_fim_str)
        colunas_entradas = [column[0] for column in cursor.description]
        entradas = [dict(zip(colunas_entradas, row)) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return render_template('resultado_produto.html', produto=produto, estoque=estoque, entradas=entradas,
                             data_inicio=data_inicio.strftime('%Y-%m-%d'), data_fim=data_fim.strftime('%Y-%m-%d'),
                             data_inicio_display=data_inicio.strftime('%d/%m/%Y'), data_fim_display=data_fim.strftime('%d/%m/%Y'),
                             data_atual=datetime.now())
    except Exception as e:
        traceback.print_exc()
        return f"Erro ao processar a consulta: {str(e)}", 500

@app.route('/api/testar_conexao', methods=['POST'])
def testar_conexao():
    data = request.json
    try:
        conn_str = (f"DRIVER={{SQL Server}};SERVER={data.get('server', '')};DATABASE={data.get('database', '')};"
                    f"UID={data.get('username', '')};PWD={data.get('password', '')}")
        conn = pyodbc.connect(conn_str)
        conn.close()
        return jsonify({'success': True, 'message': 'Conexão bem-sucedida!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro na conexão: {str(e)}'})

if __name__ == '__main__':
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: f.write('{}')
    app.run(debug=True, host='0.0.0.0', port=5001)