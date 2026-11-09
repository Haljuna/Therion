package com.therion.estacao;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.CookieSyncManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

/** Tela inicial do tablet: abre a Estação Therion em tela cheia e nunca sai dela. */
public class EstacaoActivity extends Activity {
    private static final String ESPERA = "file:///android_asset/espera.html";
    private static final String BARRA = "com.android.systemui";
    private WebView web;

    @Override
    protected void onCreate(Bundle estado) {
        super.onCreate(estado);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        CookieSyncManager.createInstance(this);
        CookieManager.getInstance().setAcceptCookie(true);
        web = new WebView(this);
        web.getSettings().setJavaScriptEnabled(true);
        web.setWebViewClient(new Cliente());
        setContentView(web);
        guardarUrl(getIntent());
        abrir();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (guardarUrl(intent)) {
            abrir();
        }
    }

    private boolean guardarUrl(Intent intent) {
        String url = intent == null ? null : intent.getStringExtra("url");
        if (url == null || url.length() == 0) {
            return false;
        }
        preferencias().edit().putString("url", url).commit();
        return true;
    }

    private SharedPreferences preferencias() {
        return getSharedPreferences("estacao", MODE_PRIVATE);
    }

    private void abrir() {
        String url = preferencias().getString("url", null);
        web.loadUrl(url == null ? ESPERA + "?semurl=1" : url);
    }

    @Override
    public void onBackPressed() {
        // A estação é a tela inicial: voltar não leva a lugar nenhum.
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieSyncManager.getInstance().sync();
    }

    private class Cliente extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            if (url.startsWith("estacao://manutencao")) {
                alternarBarra();
                return true;
            }
            return false;
        }

        @Override
        public void onReceivedError(WebView view, int codigo, String descricao, String urlFalha) {
            String url = preferencias().getString("url", "");
            view.loadUrl(ESPERA + "?url=" + Uri.encode(url));
        }
    }

    private void alternarBarra() {
        int estado = getPackageManager().getApplicationEnabledSetting(BARRA);
        final boolean desligada = estado == PackageManager.COMPONENT_ENABLED_STATE_DISABLED
                || estado == PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER;
        new Thread(new Runnable() {
            public void run() {
                final boolean ok = rodarComoRoot("pm " + (desligada ? "enable " : "disable ") + BARRA);
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (!ok) {
                            Toast.makeText(EstacaoActivity.this, "FALHOU: SEM ROOT", Toast.LENGTH_LONG).show();
                            return;
                        }
                        Toast.makeText(EstacaoActivity.this, desligada ? "BARRA LIGADA" : "BARRA DESLIGADA",
                                Toast.LENGTH_SHORT).show();
                        if (desligada) {
                            startActivity(new Intent(Settings.ACTION_SETTINGS));
                        }
                    }
                });
            }
        }).start();
    }

    private static boolean rodarComoRoot(String comando) {
        try {
            return Runtime.getRuntime().exec(new String[] {"su", "-c", comando}).waitFor() == 0;
        } catch (Exception erro) {
            return false;
        }
    }
}
