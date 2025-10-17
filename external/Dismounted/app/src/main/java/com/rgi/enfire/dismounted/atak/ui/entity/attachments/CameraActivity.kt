package com.rgi.enfire.dismounted.atak.ui.entity.attachments

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.os.Bundle
import android.provider.MediaStore
import android.util.Log

/**
 * An activity that launches the camera app and returns a bitmap of the image taken as a result.
 */
class CameraActivity : Activity() {
    /**
     * {@inheritDoc}
     */
    public override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val cameraIntent = Intent(
            MediaStore.ACTION_IMAGE_CAPTURE
        )
        startActivityForResult(cameraIntent, CAMERA_REQUEST)
    }

    /**
     * {@inheritDoc}
     */
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)

        val i = Intent(CAMERA_INFO)

        if (requestCode == CAMERA_REQUEST) {
            if (resultCode == RESULT_OK) {
                if (data != null) {
                    try {
                        val extras: Bundle? = data.extras
                        if (extras != null) {
                            val photo: Bitmap? = extras.getParcelable("data")
                            i.putExtra("image", photo)
                        }
                    } catch (e: ClassCastException) {
                        Log.e("CameraActivity", "Error casting camera data to Bitmap: ${e.message}")
                        // Handle the error (e.g., show an error message to the user)
                    } catch (e: Exception){
                        Log.e("CameraActivity", "General error processing camera result: ${e.message}")
                    }

                } else {
                    Log.e("CameraActivity", "Camera data is null (RESULT_OK)")
                    // Handle the case where data is null despite RESULT_OK
                    // this can happen on some devices.
                }
            } else if (resultCode == RESULT_CANCELED) {
                Log.d("CameraActivity", "Camera activity canceled")
                // Handle the case where the camera activity was canceled
            } else {
                Log.e("CameraActivity", "Camera activity failed with result code: $resultCode")
                // Handle other possible result codes
            }
        }

        try {
            sendBroadcast(i)
        } catch (e: Exception) {
            Log.e("CameraActivity", "Error sending broadcast: ${e.message}")
        } finally {
            finish()
        }
    }

    fun interface CameraDataReceiver {
        fun onCameraDataReceived(b: Bitmap?)
    }

    /**
     * Broadcast Receiver that is responsible for getting the data back to the
     * plugin.
     */
    internal class CameraDataListener : BroadcastReceiver() {
        private var registered = false
        private var cdr: CameraDataReceiver? = null
        @Synchronized
        fun register(
            context: Context,
            cdr: CameraDataReceiver?
        ) {
            if (!registered) context.registerReceiver(this, IntentFilter(CAMERA_INFO))
            this.cdr = cdr
            registered = true
        }

        /**
         * {@inheritDoc}
         */
        override fun onReceive(context: Context, intent: Intent) {
            synchronized(this) {
                try {
                    val extras = intent.extras
                    if (extras != null) {
                        val bm =
                            extras["image"] as Bitmap?
                        if (bm != null && cdr != null) cdr!!.onCameraDataReceived(bm)
                    }
                } catch (ignored: Exception) {
                }
                if (registered) {
                    context.unregisterReceiver(this)
                    registered = false
                }
            }
        }
    }

    companion object {
        private const val CAMERA_REQUEST = 8888
        private const val CAMERA_INFO = "com.rgi.enfire.dismounted.atak.ui.attributes.PHOTO"
    }
}
